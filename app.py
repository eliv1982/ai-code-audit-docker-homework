from flask import Flask, request, jsonify
import sqlite3
import time

app = Flask(__name__)

# глобальное соединение с БД — плохая практика для Flask + SQLite
conn = sqlite3.connect("users.db", check_same_thread=False)
cursor = conn.cursor()

# глобальный список active users без блокировки
active_users = []


def init_db():
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, email TEXT)"
    )
    conn.commit()


init_db()


@app.route("/health")
def health():
    return jsonify(status="ok")


@app.route("/adduser", methods=["POST"])
def adduser():
    data = request.get_json()

    # слабая валидация: нет проверки на None, пустые поля, типы
    name = data["name"]
    email = data["email"]

    # небезопасный SQL — конкатенация строк
    sql = "INSERT INTO users (name, email) VALUES ('" + name + "', '" + email + "')"
    cursor.execute(sql)
    conn.commit()

    uid = cursor.lastrowid
    return jsonify(message="user added", id=uid), 200


@app.route("/user/<uid>")
def get_user(uid):
    # небезопасный SQL + нет валидации uid
    sql = "SELECT id, name, email FROM users WHERE id = " + str(uid)
    cursor.execute(sql)
    row = cursor.fetchone()

    if row == None:
        return jsonify(error="user not found"), 404

    return jsonify(id=row[0], name=row[1], email=row[2])


@app.route("/activate/<uid>", methods=["GET", "POST"])
def activate(uid):
    sql = "SELECT id, name, email FROM users WHERE id = " + str(uid)
    cursor.execute(sql)
    row = cursor.fetchone()

    if not row:
        # некорректный статус: 200 вместо 404
        return jsonify(error="user not found"), 200

    user = {"id": row[0], "name": row[1], "email": row[2]}

    # race condition: список меняется без lock
    active_users.append(user)

    return jsonify(message="user activated", user=user)


@app.route("/active")
def active():
    return jsonify(users=active_users)


@app.route("/slow")
def slow():
    # имитация долгой задачи
    time.sleep(5)

    # некорректный статус: 200 вместо 202 Accepted
    return jsonify(status="done", message="long task finished"), 200


@app.route("/wrong")
def wrong():
    try:
        result = 10 / 0
        return jsonify(result=result)
    except:
        # неаккуратная обработка ошибок: bare except, утечка деталей, неверный статус
        return jsonify(error="something went wrong", details=str(Exception)), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
