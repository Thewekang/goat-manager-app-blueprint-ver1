from app import create_app

app = create_app()

print("TEMPLATE FOLDER:", app.template_folder)
print("PROJECT DIR:", __file__)

if __name__ == "__main__":
    app.run(debug=True)
