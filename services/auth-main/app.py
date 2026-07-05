from flask import Flask, render_template, session, redirect, url_for, request

app = Flask(__name__)
app.secret_key = "MASTER_SECRET_KEY" # Change this!

@app.route("/")
def dashboard():
    # In a real app, check if logged in
    # if 'user_id' not in session: return redirect('/login')
    return render_template("index.html", user_name="Admin")

@app.route("/login")
def login():
    # Your login logic here
    session['user_id'] = 'admin_1'
    return redirect(url_for('dashboard'))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)