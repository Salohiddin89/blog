from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    jsonify,
)
import sqlite3
import os
import hashlib
import uuid
from datetime import datetime
from functools import wraps
import base64
import re

app = Flask(__name__)
app.secret_key = "supersecretkey_blog_2024"
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

DB_PATH = os.path.join(os.path.dirname(__file__), "blog.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            short_desc TEXT NOT NULL,
            description TEXT NOT NULL,
            image TEXT,
            video TEXT,
            views INTEGER DEFAULT 0,
            likes INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (post_id) REFERENCES posts(id)
        );
        CREATE TABLE IF NOT EXISTS post_likes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            ip_address TEXT NOT NULL,
            UNIQUE(post_id, ip_address)
        );
        CREATE TABLE IF NOT EXISTS admin (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        );
    """)
    # Create default admin
    pwd = hashlib.sha256("admin123".encode()).hexdigest()
    try:
        c.execute(
            "INSERT INTO admin (username, password) VALUES (?, ?)", ("admin", pwd)
        )
    except:
        pass
    conn.commit()
    conn.close()


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)

    return decorated


def save_file(file_obj, allowed_ext):
    if file_obj and file_obj.filename:
        ext = file_obj.filename.rsplit(".", 1)[-1].lower()
        if ext in allowed_ext:
            filename = f"{uuid.uuid4().hex}.{ext}"
            file_obj.save(os.path.join(UPLOAD_FOLDER, filename))
            return filename
    return None


# ─── Public Routes ────────────────────────────────────────────────────────────


@app.route("/")
def index():
    conn = get_db()
    posts = conn.execute("SELECT * FROM posts ORDER BY created_at DESC").fetchall()
    conn.close()
    return render_template("index.html", posts=posts)


@app.route("/post/<int:post_id>")
def post_detail(post_id):
    conn = get_db()
    conn.execute("UPDATE posts SET views = views + 1 WHERE id = ?", (post_id,))
    conn.commit()
    post = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    comments = conn.execute(
        "SELECT * FROM comments WHERE post_id = ? ORDER BY created_at DESC", (post_id,)
    ).fetchall()
    conn.close()
    if not post:
        return redirect(url_for("index"))
    return render_template("post_detail.html", post=post, comments=comments)


@app.route("/post/<int:post_id>/comment", methods=["POST"])
def add_comment(post_id):
    first_name = request.form.get("first_name", "").strip()
    last_name = request.form.get("last_name", "").strip()
    message = request.form.get("message", "").strip()
    if first_name and last_name and message:
        conn = get_db()
        conn.execute(
            "INSERT INTO comments (post_id, first_name, last_name, message) VALUES (?, ?, ?, ?)",
            (post_id, first_name, last_name, message),
        )
        conn.commit()
        conn.close()
        flash("Komment muvaffaqiyatli qo'shildi!", "success")
    else:
        flash("Barcha maydonlarni to'ldiring!", "error")
    return redirect(url_for("post_detail", post_id=post_id))


@app.route("/post/<int:post_id>/like", methods=["POST"])
def like_post(post_id):
    ip = request.remote_addr
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO post_likes (post_id, ip_address) VALUES (?, ?)", (post_id, ip)
        )
        conn.execute("UPDATE posts SET likes = likes + 1 WHERE id = ?", (post_id,))
        conn.commit()
        liked = True
    except sqlite3.IntegrityError:
        conn.execute(
            "DELETE FROM post_likes WHERE post_id = ? AND ip_address = ?", (post_id, ip)
        )
        conn.execute("UPDATE posts SET likes = likes - 1 WHERE id = ?", (post_id,))
        conn.commit()
        liked = False
    post = conn.execute("SELECT likes FROM posts WHERE id = ?", (post_id,)).fetchone()
    conn.close()
    return jsonify({"liked": liked, "likes": post["likes"]})


@app.route("/post/<int:post_id>/liked")
def check_liked(post_id):
    ip = request.remote_addr
    conn = get_db()
    liked = conn.execute(
        "SELECT 1 FROM post_likes WHERE post_id = ? AND ip_address = ?", (post_id, ip)
    ).fetchone()
    conn.close()
    return jsonify({"liked": bool(liked)})


# ─── Admin Routes ─────────────────────────────────────────────────────────────


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if session.get("admin_logged_in"):
        return redirect(url_for("admin_dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "")
        password = hashlib.sha256(request.form.get("password", "").encode()).hexdigest()
        conn = get_db()
        admin = conn.execute(
            "SELECT * FROM admin WHERE username = ? AND password = ?",
            (username, password),
        ).fetchone()
        conn.close()
        if admin:
            session["admin_logged_in"] = True
            session["admin_username"] = username
            return redirect(url_for("admin_dashboard"))
        flash("Noto'g'ri login yoki parol!", "error")
    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))


@app.route("/admin")
@admin_required
def admin_dashboard():
    conn = get_db()
    posts = conn.execute("SELECT * FROM posts ORDER BY created_at DESC").fetchall()
    total_views = conn.execute("SELECT SUM(views) FROM posts").fetchone()[0] or 0
    total_comments = conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0] or 0
    total_likes = conn.execute("SELECT SUM(likes) FROM posts").fetchone()[0] or 0
    conn.close()
    return render_template(
        "admin_dashboard.html",
        posts=posts,
        total_views=total_views,
        total_comments=total_comments,
        total_likes=total_likes,
    )


@app.route("/admin/post/new", methods=["GET", "POST"])
@admin_required
def admin_new_post():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        short_desc = request.form.get("short_desc", "").strip()
        description = request.form.get("description", "").strip()
        video = request.form.get("video", "").strip()
        image_file = request.files.get("image")
        image = save_file(image_file, {"jpg", "jpeg", "png", "gif", "webp"})
        if title and short_desc and description:
            conn = get_db()
            conn.execute(
                "INSERT INTO posts (title, short_desc, description, image, video) VALUES (?, ?, ?, ?, ?)",
                (title, short_desc, description, image, video or None),
            )
            conn.commit()
            conn.close()
            flash("Post muvaffaqiyatli qo'shildi!", "success")
            return redirect(url_for("admin_dashboard"))
        flash("Barcha majburiy maydonlarni to'ldiring!", "error")
    return render_template("admin_post_form.html", post=None)


@app.route("/admin/post/<int:post_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_edit_post(post_id):
    conn = get_db()
    post = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    conn.close()
    if not post:
        return redirect(url_for("admin_dashboard"))
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        short_desc = request.form.get("short_desc", "").strip()
        description = request.form.get("description", "").strip()
        video = request.form.get("video", "").strip()
        image_file = request.files.get("image")
        image = save_file(image_file, {"jpg", "jpeg", "png", "gif", "webp"})
        conn = get_db()
        if image:
            conn.execute(
                "UPDATE posts SET title=?, short_desc=?, description=?, image=?, video=? WHERE id=?",
                (title, short_desc, description, image, video or None, post_id),
            )
        else:
            conn.execute(
                "UPDATE posts SET title=?, short_desc=?, description=?, video=? WHERE id=?",
                (title, short_desc, description, video or None, post_id),
            )
        conn.commit()
        conn.close()
        flash("Post yangilandi!", "success")
        return redirect(url_for("admin_dashboard"))
    return render_template("admin_post_form.html", post=post)


@app.route("/admin/post/<int:post_id>/delete", methods=["POST"])
@admin_required
def admin_delete_post(post_id):
    conn = get_db()
    post = conn.execute("SELECT image FROM posts WHERE id = ?", (post_id,)).fetchone()
    if post and post["image"]:
        img_path = os.path.join(UPLOAD_FOLDER, post["image"])
        if os.path.exists(img_path):
            os.remove(img_path)
    conn.execute("DELETE FROM comments WHERE post_id = ?", (post_id,))
    conn.execute("DELETE FROM post_likes WHERE post_id = ?", (post_id,))
    conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))
    conn.commit()
    conn.close()
    flash("Post o'chirildi!", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/comments")
@admin_required
def admin_comments():
    conn = get_db()
    comments = conn.execute(
        "SELECT c.*, p.title as post_title FROM comments c JOIN posts p ON c.post_id = p.id ORDER BY c.created_at DESC"
    ).fetchall()
    conn.close()
    return render_template("admin_comments.html", comments=comments)


@app.route("/admin/comment/<int:comment_id>/delete", methods=["POST"])
@admin_required
def admin_delete_comment(comment_id):
    conn = get_db()
    conn.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
    conn.commit()
    conn.close()
    flash("Komment o'chirildi!", "success")
    return redirect(url_for("admin_comments"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=True)
