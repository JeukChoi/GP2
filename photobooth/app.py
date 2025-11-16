from flask import Flask, render_template, request, jsonify, send_from_directory, send_file, session, url_for
import os
from PIL import Image, ImageDraw, ImageFont
import qrcode
import datetime
import base64
import uuid
import json
from io import BytesIO


app = Flask(__name__)
app.secret_key = '비공개개'  # 세션 관리를 위한 시크릿 키 설정


# 기본 디렉토리 및 사진 저장 경로 설정
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PHOTO_DIR = os.path.join(BASE_DIR, 'static', 'photos', 'raw')  # 원본 사진 저장 폴더
COMPOSITE_DIR = os.path.join(BASE_DIR, 'static', 'photos', 'composite')  # 합성된 사진 저장 폴더


# 사진 저장을 위한 디렉토리 존재 여부 확인 및 생성
for p in [PHOTO_DIR, COMPOSITE_DIR]:
    if not os.path.exists(p):
        os.makedirs(p)


# index 렌더링 및 세션 초기화 후 세션 ID 생성
@app.route('/')
def index():
    session.clear()
    session['session_id'] = str(uuid.uuid4())  # 중복 방지 위한 세션별 고유 ID 생성
    return render_template('index.html')



# selectFrame 렌더링. 세션 ID 전달
@app.route('/selectFrame')
def select_frame():
    return render_template('selectFrame.html', session_id=session.get('session_id'))



# shoot 렌더링
@app.route('/shoot')
def shoot():
    return render_template('shoot.html')



# selectPhoto 렌더링
@app.route('/selectPhoto')
def select_photo():
    return render_template('selectPhoto.html')



# downolad 렌더링
@app.route('/download')
def download():
    img_url = request.args.get('img_url')
    if not img_url:
        return "이미지 정보가 없습니다.", 400
    return render_template('download.html', img_url=img_url)



# 촬영된 사진 데이터(base64) 수신 후 세션별 폴더에 png로 저장
@app.route('/save_photo', methods=['POST'])
def save_photo():
    data = request.json
    img_data = data.get('image_data')
    img_index = data.get('index')
    session_id = data.get('session_id')

    # 필수 데이터 체크
    if not img_data or img_index is None or not session_id:
        return jsonify({'success': False, 'message': 'Invalid data'}), 400

    session_folder = os.path.join(PHOTO_DIR, session_id)
    if not os.path.exists(session_folder):
        os.makedirs(session_folder)

    try:
        header, encoded = img_data.split(',', 1)
        filename = f'photo_{img_index}.png'
        filepath = os.path.join(session_folder, filename)
        # base64 디코딩 후 이미지 파일로 저장
        with open(filepath, 'wb') as f:
            f.write(base64.b64decode(encoded))
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

    return jsonify({'success': True, 'filename': filename})



# 특정 세션에 저장된 사진 파일 목록을 JSON으로 반환
@app.route('/list_photos/<session_id>', methods=['GET'])
def list_photos(session_id):
    session_folder = os.path.join(PHOTO_DIR, session_id)
    if not os.path.exists(session_folder):
        return jsonify({'success': False, 'photos': [], 'message': '세션이 없습니다.'})

    photos = sorted(f for f in os.listdir(session_folder) if f.lower().endswith(('.png', '.jpg', '.jpeg')))
    photo_urls = [f'/static/photos/raw/{session_id}/{photo}' for photo in photos]

    return jsonify({'success': True, 'photos': photo_urls})



# 선택된 4장 사진과 프레임 이미지를 합성하여 하나의 결과물 생성 및 저장
def compose_photo_with_frame(session_id, frame_img, photo_images, composite_path, composite_link):

    # 사진 크기 및 위치 고정
    w, h = 1205, 1795
    base = Image.new('RGB', (w, h), (255, 255, 255))
    photo_w, photo_h = 533, 698
    positions = [
        (int(w * 0.0352), int(h * 0.0261)),
        (int(w * 0.5232), int(h * 0.0261)),
        (int(w * 0.0352), int(h * 0.4373)),
        (int(w * 0.5232), int(h * 0.4373)),
    ]
    for idx, img in enumerate(photo_images):
        img = img.resize((photo_w, photo_h))
        base.paste(img, positions[idx])

    frame = frame_img.convert('RGBA').resize((w, h))
    base = base.convert('RGBA')
    base = Image.alpha_composite(base, frame)

    # 현재 날짜 텍스트 삽입
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    draw = ImageDraw.Draw(base)
    font_path = "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"
    font = ImageFont.truetype(font_path, 20)
    bbox = draw.textbbox((0, 0), today, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    text_x = (w - text_w) // 2
    text_y = h - text_h - 30
    draw.text((text_x, text_y), today, fill=(20, 20, 20), font=font)

    # QR 코드 생성 및 삽입
    qr_img = qrcode.make(composite_link)
    qr_size = 90
    qr_img = qr_img.resize((qr_size, qr_size))
    base.paste(qr_img.convert('RGBA'), (w - qr_size - 36, h - qr_size - 24), qr_img.convert('RGBA'))

    base = base.convert('RGB')
    base.save(composite_path)



@app.route('/save_selection', methods=['POST'])
def save_selection():
    # 요청 데이터에서 세션 ID, 선택한 사진 리스트, 프레임 파일명을 추출
    data = request.json
    session_id = data.get('session_id')
    selected_photos = data.get('selected_photos')
    frame_file_name = data.get('frame_file')

    # 데이터 필수값 검증
    if not session_id or not isinstance(selected_photos, list) or len(selected_photos) != 4 or not frame_file_name:
        return jsonify({'success': False, 'message': 'Invalid data'}), 400

    # 세션별 폴더가 존재하는지 확인
    session_folder = os.path.join(PHOTO_DIR, session_id)
    if not os.path.exists(session_folder):
        return jsonify({'success': False, 'message': '세션이 없습니다.'}), 404

    # 선택한 번호(4장) 순서대로 사진 파일 경로 생성
    photo_paths = [os.path.join(session_folder, f'photo_{num}.png') for num in selected_photos]

    # 프레임 파일(오버레이 이미지) 경로 생성하며 존재 여부 확인
    frame_path = os.path.join(BASE_DIR, 'static', 'images', frame_file_name)
    if not os.path.exists(frame_path):
        return jsonify({'success': False, 'message': '프레임 이미지가 없습니다.'}), 404

    try:
        # PIL을 이용해서 선택된 각 사진 이미지 객체 리스트 생성
        photo_images = [Image.open(p) for p in photo_paths]

        # 합성 결과물 파일 이름 및 경로 동적 생성(UUID로 중복 방지, jpg로 저장)
        composite_filename = f"{session_id}_{str(uuid.uuid4())[:8]}_composite.jpg"
        composite_path = os.path.join(COMPOSITE_DIR, composite_filename)
        composite_link = url_for('serve_composite', filename=composite_filename, _external=True)

        # 프레임 이미지 열고, 사진들 + 프레임을 합성하는 함수 실행
        frame_img = Image.open(frame_path)
        compose_photo_with_frame(session_id, frame_img, photo_images, composite_path, composite_link)

    except Exception as e:
        # 이미지 파일 열기/합성 중 예외 발생 시 에러 메시지와 함께 500 반환
        return jsonify({'success': False, 'message': str(e)}), 500

    # 합성 완료 후 download 페이지 URL 응답으로 전달
    return jsonify({'success': True, 'redirect_url': url_for('download', img_url=composite_link)})



# 합성된 사진 파일 직접 서빙-> URL로 접근 가능
@app.route('/static/photos/composite/<filename>')
def serve_composite(filename):
    return send_from_directory(COMPOSITE_DIR, filename)



# 입력된 URL 기반으로 QR 코드 이미지 생성 및 반환
@app.route('/generate_qr')
def generate_qr():
    url = request.args.get('url')
    if not url:
        return 'URL parameter missing', 400

    qr_img = qrcode.make(url)
    img_io = BytesIO()
    qr_img.save(img_io, 'PNG')
    img_io.seek(0)
    return send_file(img_io, mimetype='image/png')



if __name__ == '__main__':
    app.run(debug=True)
