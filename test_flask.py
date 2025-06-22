from flask import Flask, render_template
app = Flask(__name__)
@app.route("/")
def hello():
    return render_template("login.html")
if __name__ == "__main__":
    print("TEMPLATE FOLDER:", app.template_folder)
    app.run(debug=True)
