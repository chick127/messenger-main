# app.py — Flask + SocketIO + RSA/AES Messenger (최종 완성본)

import os
import sys
import base64
from functools import wraps

# --- crypto 폴더 경로 추가 ---
# app.py가 루트 디렉토리에 있으므로, BASE_DIR은 현재 파일의 디렉토리가 되어야 합니다.
BASE_DIR = os.path.dirname(os.path.abspath(__file__)) 
CRYPTO_DIR = os.path.join(BASE_DIR, 'crypto')
sys.path.append(CRYPTO_DIR)

# --- 암호화 모듈 가져오기 ---
try:
    # crypto 폴더가 루트에 있다면 이 경로는 올바르게 작동해야 합니다.
    from aes_module import AESCipher
    from rsa_module import RSACipher
except ImportError:
    # Vercel 빌드 환경에서는 이 메시지가 보일 수 있습니다.
    print("FATAL ERROR: crypto 모듈을 불러올 수 없습니다. 경로 확인 필요:", CRYPTO_DIR)
    sys.exit(1)

# --- Flask & SocketIO ---
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room
from cryptography.exceptions import InvalidTag
# Flask-SocketIO가 eventlet을 사용하도록 강제 (Vercel에서 권장)
import eventlet 
eventlet.monkey_patch() 


# 1. Flask + SocketIO 생성
# Vercel에서는 WSGI/ASGI 앱만 필요하므로, 이 파일에서 WSGI/ASGI 앱을 export 해야 합니다.
app = Flask(__name__)
# Secret Key는 환경 변수로 설정하는 것이 좋습니다.
app.secret_key = os.environ.get('FLASK_SECRET_KEY', os.urandom(24)) 
# Vercel 환경에서 SocketIO 설정 (WebSocket 연결 허용)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet') 

# 2. 임시 저장소 (Serverless Function이므로 매번 초기화됨을 인지해야 함)
# 실제 프로덕션에서는 Redis나 데이터베이스를 사용해야 합니다.
USERS = {}
SESSION_KEYS = {}

# 3. 서버 시작 시 RSA 키 생성
def initialize_users():
    # USERS 딕셔너리가 비어있을 때만 초기화
    if not USERS:
        USERS['Alice'] = RSACipher()
        USERS['Bob'] = RSACipher()
        print("--- 서버 초기화 완료 (Alice, Bob RSA 키 생성) ---")

# initialize_users는 라우팅이나 이벤트가 호출될 때 실행되도록 변경
# Vercel Serverless Function은 cold start 시에만 실행됨

# 4. 라우팅
@app.route('/')
def index():
    initialize_users() # 요청 시 초기화 체크
    return render_template('index.html', users=USERS.keys())


@app.route('/messenger/<sender>', methods=['GET'])
def messenger(sender):
    initialize_users() # 요청 시 초기화 체크
    if sender not in USERS:
        return "사용자 오류", 404

    recipient = 'Bob' if sender == 'Alice' else 'Alice'

    # AES 키 생성
    aes_cipher = AESCipher()
    aes_key_bytes = aes_cipher.get_key_bytes()

    # RSA 공개키 취득
    recipient_pub = USERS[recipient].get_public_key()

    try:
        # RSA 로 AES 키 암호화 (송신자 역할)
        encrypted_key = USERS[sender].encrypt(
            aes_key_bytes.decode('latin-1'),
            recipient_pub
        )

        # 수신자 복호화
        decrypted_key = USERS[recipient].decrypt(encrypted_key)
        decrypted_key_bytes = decrypted_key.encode('latin-1')

        if decrypted_key_bytes != aes_key_bytes:
            return "키 교환 실패", 500

        # 세션키 할당
        SESSION_KEYS[sender] = aes_cipher
        SESSION_KEYS[recipient] = AESCipher(key_bytes=decrypted_key_bytes)

        snippet = base64.b64encode(aes_key_bytes)[:10].decode() + "..."
        print(f"🔑 키 교환 성공: {sender} <-> {recipient} (AES 키: {snippet})")

        return render_template(
            'message.html',
            sender=sender,
            recipient=recipient,
            key_exchange_status="성공",
            session_key_snippet=snippet
        )

    except Exception as e:
        print("키 교환 오류:", e)
        return "키 교환 오류 발생", 500

# 5. SocketIO 이벤트
@socketio.on('connect')
def handle_connect():
    print(f"클라이언트 연결: {request.sid}")

@socketio.on('register_user')
def handle_register_user(data):
    initialize_users() # 이벤트 발생 시 초기화 체크
    username = data.get('username')
    if username in USERS:
        join_room(username)
        print(f"사용자 등록: {username} (SID: {request.sid})")
        emit('status_update', {'msg': f'{username}님 연결됨!'}, room=request.sid)


@socketio.on('send_message')
def handle_send_message(data):
    initialize_users() # 이벤트 발생 시 초기화 체크
    sender = data.get('sender')
    recipient = data.get('recipient')
    message = data.get('message')

    # ... (나머지 SocketIO 로직은 동일) ...

    if sender not in SESSION_KEYS or recipient not in SESSION_KEYS:
        emit('status_update', {'msg': '세션 키 없음'}, room=sender)
        return

    sender_cipher = SESSION_KEYS[sender]
    associated_data = f"{sender} to {recipient}".encode('utf-8')

    # ① AES 암호화
    encrypted_b64 = sender_cipher.encrypt(message, associated_data=associated_data)

    print(f"\n[SocketIO 송신: {sender} -> {recipient}]")
    print(f"  원본 메시지: '{message}'")
    print(f"  암호문 (B64): '{encrypted_b64}'")

    # ② 복호화 시뮬레이션 및 무결성 검증 (수신자 역할 시뮬레이션)
    decrypted_message = None
    recipient_cipher = SESSION_KEYS[recipient]
    integrity_verified = False

    try:
        # 수신자가 암호문을 받아서 GCM 태그 검증 및 복호화 시도
        decrypted_message = recipient_cipher.decrypt(
            encrypted_b64,
            associated_data=associated_data
        )

        # 태그 검증 성공: T_new == T' (수신된 태그와 계산된 태그 일치)
        integrity_verified = True
        print(f"[수신 시뮬레이션: {recipient}] ✅ 무결성 검증 성공 (T_new == T') → 복호화 성공: '{decrypted_message}'")
        decrypt_status = f"✅ 무결성 검증 성공: '{decrypted_message}'"

    except InvalidTag:
        # 태그 검증 실패: T_new != T' (메시지 변조 또는 위조)
        integrity_verified = False
        decrypted_message = None
        print(f"[수신 시뮬레이션: {recipient}] ❌ 무결성 검증 실패 (T_new != T') - GCM TAG 오류: 메시지 변조 또는 위조")
        decrypt_status = "❌ 무결성 검증 실패 - 메시지 변조 또는 위조 감지"

    except Exception as e:
        integrity_verified = False
        decrypted_message = None
        print(f"[수신 시뮬레이션: {recipient}] 오류: {e}")
        decrypt_status = f"❌ 오류: {e}"

    # ③ 수신자에게 메시지 전달 (복호문 포함!)
    message_payload = {
        'sender': sender,
        'encrypted_data': encrypted_b64,
        'associated_data': associated_data.decode(),
        'decrypted_message': decrypted_message
    }

    socketio.emit('new_message', message_payload, room=recipient)

    # ④ 송신자에게 결과 전달
    emit(
        'send_success',
        {
            'original_message': message,
            'encrypted_message': encrypted_b64,
            'decryption_status': decrypt_status
        },
        room=sender
    )


# Vercel용 WSGI app export (SocketIO를 Flask 앱의 WSGI 래퍼로 사용)
# Flask-SocketIO 앱을 Vercel에 노출하는 올바른 방식입니다.
application = socketio.wsgi_app

# 로컬 실행용
if __name__ == '__main__':
    # 로컬에서는 socketio.run을 사용하여 eventlet 서버를 실행합니다.
    socketio.run(app, debug=True, port=int(os.environ.get('PORT', 5000)))