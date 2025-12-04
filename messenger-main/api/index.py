from flask import Flask, render_template

app = Flask(__name__)

@app.route('/')
def home():
    # HTML 템플릿을 렌더링하거나 간단한 응답을 반환
    return '<h1>Hello from Python Vercel Function!</h1>'

# Vercel은 이 'app' 변수를 Serverless Function의 진입점(Entry Point)으로 사용합니다.