#!/usr/bin/env python3
"""Todo-app Flask backend"""

from flask import Flask, jsonify, request, render_template, send_from_directory
from datetime import datetime, date, timedelta
from pathlib import Path
import json
import re
import os

app = Flask(__name__)
DATA_FILE = Path.home() / ".todo.json"

REPEAT_LABELS = {
    "daily": "varje dag", "weekly": "varje vecka",
    "monthly": "varje månad", "weekdays": "vardagar",
}
WEEKDAYS  = ["måndag","tisdag","onsdag","torsdag","fredag","lördag","söndag"]
MONTHS_SV = {
    "januari":1,"februari":2,"mars":3,"april":4,"maj":5,"juni":6,
    "juli":7,"augusti":8,"september":9,"oktober":10,"november":11,"december":12,
    "jan":1,"feb":2,"mar":3,"apr":4,"jun":6,"jul":7,"aug":8,
    "sep":9,"okt":10,"nov":11,"dec":12,
}

# ── data ───────────────────────────────────────────────────────────────────────

def load():
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text())
        except Exception:
            pass
    return {"tasks": [], "_next_id": 1}

def save(data):
    DATA_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))

def today_str():
    return date.today().isoformat()

def parse_date(s):
    s = s.strip().lower()
    today = date.today()
    if s in ("idag","nu"):         return today.isoformat()
    if s == "imorgon":             return (today + timedelta(days=1)).isoformat()
    if s == "övermorgon":          return (today + timedelta(days=2)).isoformat()
    if s == "nästa vecka":         return (today + timedelta(weeks=1)).isoformat()
    if s in WEEKDAYS:
        delta = (WEEKDAYS.index(s) - today.weekday()) % 7 or 7
        return (today + timedelta(days=delta)).isoformat()
    m = re.match(r"om\s+(\d+)\s+(dag|dagar|vecka|veckor|månad|månader)", s)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        if "dag" in unit:   return (today + timedelta(days=n)).isoformat()
        if "vecka" in unit: return (today + timedelta(weeks=n)).isoformat()
        if "månad" in unit:
            mo = today.month + n; yr = today.year + (mo-1)//12; mo = (mo-1)%12+1
            try:    return today.replace(year=yr, month=mo).isoformat()
            except: return today.replace(year=yr, month=mo, day=28).isoformat()
    m = re.match(r"(\d{1,2})\s+([a-zåäö]+)(?:\s+(\d{4}))?$", s)
    if m:
        day = int(m.group(1)); mon = MONTHS_SV.get(m.group(2))
        yr  = int(m.group(3)) if m.group(3) else today.year
        if mon:
            d = date(yr, mon, day)
            if d < today and not m.group(3): d = date(yr+1, mon, day)
            return d.isoformat()
    try:    return datetime.strptime(s, "%Y-%m-%d").date().isoformat()
    except: pass
    try:    return datetime.strptime(s, "%d/%m/%Y").date().isoformat()
    except: pass
    try:
        d = datetime.strptime(s, "%d/%m").date().replace(year=today.year)
        if d < today: d = d.replace(year=today.year+1)
        return d.isoformat()
    except: pass
    raise ValueError(f"Förstår inte datumet '{s}'")

def next_occurrence(task):
    repeat = task.get("repeat")
    base   = date.fromisoformat(task.get("last_done") or task.get("due") or today_str())
    if repeat == "daily":    return (base + timedelta(days=1)).isoformat()
    if repeat == "weekly":   return (base + timedelta(weeks=1)).isoformat()
    if repeat == "weekdays":
        d = base + timedelta(days=1)
        while d.weekday() >= 5: d += timedelta(days=1)
        return d.isoformat()
    if repeat == "monthly":
        mo = base.month+1; yr = base.year+(mo-1)//12; mo = (mo-1)%12+1
        try:    return base.replace(year=yr, month=mo).isoformat()
        except: return base.replace(year=yr, month=mo, day=28).isoformat()
    return None

def enrich(task):
    """Add computed display fields."""
    t = dict(task)
    due = t.get("due")
    if due:
        d    = date.fromisoformat(due)
        diff = (d - date.today()).days
        if diff < 0:   t["due_label"] = f"Försenad {abs(diff)}d"
        elif diff == 0: t["due_label"] = "Idag"
        elif diff == 1: t["due_label"] = "Imorgon"
        elif diff <= 7: t["due_label"] = f"Om {diff}d ({WEEKDAYS[d.weekday()]})"
        else:           t["due_label"] = due
        t["overdue"]    = diff < 0 and not task.get("done")
        t["due_today"]  = diff == 0 and not task.get("done")
        t["due_soon"]   = 0 < diff <= 3 and not task.get("done")
    else:
        t["due_label"] = ""
        t["overdue"] = t["due_today"] = t["due_soon"] = False
    t["repeat_label"] = REPEAT_LABELS.get(t.get("repeat",""), "")
    return t

# ── API ────────────────────────────────────────────────────────────────────────

@app.route("/api/tasks", methods=["GET"])
def get_tasks():
    data   = load()
    filter_= request.args.get("filter", "active")
    tasks  = [enrich(t) for t in data["tasks"]]
    if filter_ == "today":
        tasks = [t for t in tasks if not t.get("done") and
                 (t.get("due_today") or t.get("overdue"))]
    elif filter_ == "active":
        tasks = [t for t in tasks if not t.get("done")]
    elif filter_ == "done":
        tasks = [t for t in tasks if t.get("done")]
    # sort: overdue first, then by due date, then no date
    def sort_key(t):
        if t.get("overdue"):   return (0, t.get("due",""))
        if t.get("due_today"): return (1, t.get("due",""))
        if t.get("due"):       return (2, t.get("due",""))
        return (3, "")
    tasks.sort(key=sort_key)
    return jsonify(tasks)

@app.route("/api/tasks", methods=["POST"])
def create_task():
    data = load()
    body = request.json or {}
    task = {
        "id":          data["_next_id"],
        "title":       body.get("title","").strip(),
        "created":     today_str(),
        "done":        False,
        "due":         None,
        "remind_time": body.get("remind_time") or None,
        "repeat":      body.get("repeat") or None,
        "priority":    body.get("priority") or None,
        "category":    body.get("category","").strip() or None,
        "note":        body.get("note","").strip() or None,
        "last_done":   None,
    }
    if not task["title"]:
        return jsonify({"error": "Titel krävs"}), 400
    if body.get("due"):
        try:    task["due"] = parse_date(body["due"])
        except ValueError as e: return jsonify({"error": str(e)}), 400
    if task["repeat"] and not task["due"]:
        task["due"] = today_str()
    data["_next_id"] += 1
    data["tasks"].append(task)
    save(data)
    return jsonify(enrich(task)), 201

@app.route("/api/tasks/<int:tid>", methods=["PUT"])
def update_task(tid):
    data = load()
    for task in data["tasks"]:
        if task["id"] == tid:
            body = request.json or {}
            if "title"       in body: task["title"]       = body["title"].strip()
            if "note"        in body: task["note"]        = body["note"].strip() or None
            if "remind_time" in body: task["remind_time"] = body["remind_time"] or None
            if "repeat"      in body: task["repeat"]      = body["repeat"] or None
            if "priority"    in body: task["priority"]    = body["priority"] or None
            if "category"    in body: task["category"]    = body["category"].strip() or None
            if "due" in body:
                if body["due"]:
                    try:    task["due"] = parse_date(body["due"])
                    except ValueError as e: return jsonify({"error": str(e)}), 400
                else:
                    task["due"] = None
            save(data)
            return jsonify(enrich(task))
    return jsonify({"error": "Hittades inte"}), 404

@app.route("/api/tasks/<int:tid>", methods=["DELETE"])
def delete_task(tid):
    data   = load()
    before = len(data["tasks"])
    data["tasks"] = [t for t in data["tasks"] if t["id"] != tid]
    if len(data["tasks"]) < before:
        save(data)
        return jsonify({"ok": True})
    return jsonify({"error": "Hittades inte"}), 404

@app.route("/api/tasks/<int:tid>/done", methods=["POST"])
def mark_done(tid):
    data = load()
    for task in data["tasks"]:
        if task["id"] == tid:
            if task.get("repeat"):
                task["last_done"] = today_str()
                task["due"]       = next_occurrence(task)
            else:
                task["done"]      = True
                task["last_done"] = today_str()
            save(data)
            return jsonify(enrich(task))
    return jsonify({"error": "Hittades inte"}), 404

@app.route("/api/tasks/<int:tid>/undone", methods=["POST"])
def mark_undone(tid):
    data = load()
    for task in data["tasks"]:
        if task["id"] == tid:
            task["done"] = False
            save(data)
            return jsonify(enrich(task))
    return jsonify({"error": "Hittades inte"}), 404

@app.route("/api/tasks/<int:tid>/snooze", methods=["POST"])
def snooze_task(tid):
    data = load()
    body = request.json or {}
    days = int(body.get("days", 1))
    for task in data["tasks"]:
        if task["id"] == tid:
            cur = date.fromisoformat(task.get("due") or today_str())
            task["due"] = (cur + timedelta(days=days)).isoformat()
            save(data)
            return jsonify(enrich(task))
    return jsonify({"error": "Hittades inte"}), 404

@app.route("/api/stats")
def get_stats():
    data  = load()
    tasks = data["tasks"]
    today = today_str()
    active   = [t for t in tasks if not t.get("done")]
    done     = [t for t in tasks if t.get("done")]
    overdue  = [t for t in active if t.get("due") and t["due"] < today]
    due_tod  = [t for t in active if t.get("due") == today]
    cats = {}
    for t in active:
        c = t.get("category") or "Övrigt"
        cats[c] = cats.get(c, 0) + 1
    return jsonify({
        "total": len(tasks), "active": len(active), "done": len(done),
        "overdue": len(overdue), "due_today": len(due_tod),
        "categories": cats,
    })

@app.route("/api/categories")
def get_categories():
    data = load()
    cats = sorted(set(
        t.get("category") for t in data["tasks"] if t.get("category")
    ))
    return jsonify(cats)

# ── PWA static files ───────────────────────────────────────────────────────────

@app.route("/manifest.json")
def manifest():
    return send_from_directory("static", "manifest.json")

@app.route("/sw.js")
def service_worker():
    return send_from_directory("static", "sw.js",
                               mimetype="application/javascript")

@app.route("/")
def index():
    return render_template("index.html")

if __name__ == "__main__":
    import socket
    host = "0.0.0.0"
    port = 5000
    ip   = socket.gethostbyname(socket.gethostname())
    print(f"\n  Todo-appen körs!")
    print(f"  Öppna i webbläsare: http://localhost:{port}")
    print(f"  Från annat nätverk: http://{ip}:{port}")
    print(f"  Stoppa: Ctrl+C\n")
    app.run(host=host, port=port, debug=False)
