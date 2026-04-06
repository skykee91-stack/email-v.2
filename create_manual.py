"""N플레이스 업체 추출기 - 설치/사용 가이드 PDF 생성"""

import os
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib.colors import HexColor, white, black
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.styles import getSampleStyleSheet
from PIL import Image, ImageDraw, ImageFont

# 폰트 등록
pdfmetrics.registerFont(TTFont("Malgun", "C:/Windows/Fonts/malgun.ttf"))
pdfmetrics.registerFont(TTFont("MalgunBold", "C:/Windows/Fonts/malgunbd.ttf"))

OUTPUT = "N플레이스_업체추출기_설치가이드.pdf"
GREEN = HexColor("#03C75A")
DARK = HexColor("#1a1a2e")
GRAY = HexColor("#666666")
LIGHT_GRAY = HexColor("#f0f0f0")
BLUE = HexColor("#2980b9")

W, H = A4  # 595 x 842


def create_step_image(filename, step_num, title, elements, width=500, height=300):
    """단계별 설명 이미지를 생성한다."""
    img = Image.new("RGB", (width, height), (245, 245, 248))
    draw = ImageDraw.Draw(img)

    try:
        font_title = ImageFont.truetype("C:/Windows/Fonts/malgunbd.ttf", 20)
        font_body = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 15)
        font_small = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 12)
        font_code = ImageFont.truetype("C:/Windows/Fonts/consola.ttf", 13)
    except:
        font_title = ImageFont.load_default()
        font_body = font_title
        font_small = font_title
        font_code = font_title

    # 상단 바
    draw.rectangle([0, 0, width, 50], fill=(3, 199, 90))
    draw.text((15, 12), f"STEP {step_num}", fill="white", font=font_title)
    draw.text((110, 16), title, fill="white", font=font_body)

    # 내용
    y = 70
    for elem in elements:
        if elem.startswith(">>"):
            # 코드 블록
            code = elem[2:].strip()
            draw.rectangle([20, y - 3, width - 20, y + 25], fill=(40, 44, 52))
            draw.text((30, y), code, fill=(0, 255, 136), font=font_code)
            y += 35
        elif elem.startswith("!!"):
            # 강조 박스
            text = elem[2:].strip()
            draw.rectangle([20, y - 3, width - 20, y + 25], fill=(255, 243, 205))
            draw.rectangle([20, y - 3, 24, y + 25], fill=(255, 193, 7))
            draw.text((35, y), text, fill=(100, 70, 0), font=font_body)
            y += 35
        elif elem.startswith("**"):
            # 볼드 텍스트
            text = elem[2:].strip()
            draw.text((25, y), text, fill=(30, 30, 30), font=font_body)
            y += 28
        elif elem.startswith("--"):
            # 구분선
            draw.line([20, y + 5, width - 20, y + 5], fill=(200, 200, 200), width=1)
            y += 15
        elif elem.startswith("[IMG:"):
            # 폴더 아이콘 시뮬레이션
            text = elem[5:-1]
            draw.rectangle([30, y, 90, y + 50], fill=(255, 220, 100), outline=(200, 170, 50))
            draw.text((35, y + 15), "📁", font=font_body)
            draw.text((100, y + 15), text, fill=(30, 30, 30), font=font_body)
            y += 60
        else:
            draw.text((25, y), elem, fill=(60, 60, 60), font=font_body)
            y += 25

    img.save(filename)
    return filename


def draw_page_header(c, page_num, total_pages):
    """페이지 상단 헤더"""
    c.setFillColor(GREEN)
    c.rect(0, H - 20 * mm, W, 20 * mm, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("MalgunBold", 12)
    c.drawString(15 * mm, H - 14 * mm, "N플레이스 업체 추출기 - 설치 및 사용 가이드")
    c.setFont("Malgun", 9)
    c.drawRightString(W - 15 * mm, H - 14 * mm, f"{page_num} / {total_pages}")


def draw_page_footer(c):
    """페이지 하단 푸터"""
    c.setFillColor(GRAY)
    c.setFont("Malgun", 8)
    c.drawCentredString(W / 2, 10 * mm, "MASTER INSIGHT co. | N플레이스 업체 추출기 v2.1")


def build_pdf():
    c = canvas.Canvas(OUTPUT, pagesize=A4)
    total_pages = 5

    # ━━━━━ 표지 (1페이지) ━━━━━
    # 배경
    c.setFillColor(DARK)
    c.rect(0, 0, W, H, fill=1, stroke=0)

    # 초록색 상단 바
    c.setFillColor(GREEN)
    c.rect(0, H - 80 * mm, W, 80 * mm, fill=1, stroke=0)

    # 로고
    logo_path = "logo.png"
    if os.path.exists(logo_path):
        c.drawImage(logo_path, W / 2 - 30 * mm, H - 70 * mm, 60 * mm, 60 * mm,
                     preserveAspectRatio=True, mask="auto")

    # 타이틀
    c.setFillColor(white)
    c.setFont("MalgunBold", 32)
    c.drawCentredString(W / 2, H - 120 * mm, "N플레이스 업체 추출기")

    c.setFont("Malgun", 16)
    c.drawCentredString(W / 2, H - 135 * mm, "설치 및 사용 가이드")

    c.setFont("Malgun", 12)
    c.setFillColor(HexColor("#888888"))
    c.drawCentredString(W / 2, H - 155 * mm, "Version 2.1")

    # 하단 정보 박스
    box_y = 60 * mm
    c.setFillColor(HexColor("#252540"))
    c.roundRect(40 * mm, box_y, W - 80 * mm, 60 * mm, 5 * mm, fill=1, stroke=0)

    c.setFillColor(HexColor("#aaaaaa"))
    c.setFont("Malgun", 11)
    info_lines = [
        "네이버 플레이스 / 블로그에서 업체 정보를 자동 수집",
        "업체명 · 전화번호 · 주소 · 네이버ID · 이메일 추출",
        "엑셀 파일로 자동 저장",
    ]
    for i, line in enumerate(info_lines):
        c.drawCentredString(W / 2, box_y + 42 * mm - i * 16, line)

    c.setFillColor(HexColor("#666666"))
    c.setFont("Malgun", 9)
    c.drawCentredString(W / 2, 35 * mm, "MASTER INSIGHT co.")

    c.showPage()

    # ━━━━━ 2페이지: 설치 방법 ━━━━━
    draw_page_header(c, 2, total_pages)
    draw_page_footer(c)

    y = H - 35 * mm

    c.setFillColor(black)
    c.setFont("MalgunBold", 20)
    c.drawString(15 * mm, y, "1. 설치 방법")
    y -= 15 * mm

    # STEP 1
    c.setFillColor(GREEN)
    c.roundRect(15 * mm, y - 55 * mm, W - 30 * mm, 55 * mm, 3 * mm, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("MalgunBold", 14)
    c.drawString(22 * mm, y - 10 * mm, "STEP 1  파일 받기")
    c.setFont("Malgun", 11)
    c.drawString(22 * mm, y - 25 * mm, "① 전달받은 'N플레이스업체추출기.zip' 파일을 바탕화면에 저장합니다.")
    c.drawString(22 * mm, y - 38 * mm, "② 파일 크기: 약 150MB")
    c.drawString(22 * mm, y - 50 * mm, "③ Python 설치 불필요 - 실행파일에 모두 포함되어 있습니다.")
    y -= 65 * mm

    # STEP 2
    c.setFillColor(LIGHT_GRAY)
    c.roundRect(15 * mm, y - 65 * mm, W - 30 * mm, 65 * mm, 3 * mm, fill=1, stroke=0)
    c.setFillColor(black)
    c.setFont("MalgunBold", 14)
    c.drawString(22 * mm, y - 10 * mm, "STEP 2  압축 해제")
    c.setFont("Malgun", 11)
    steps = [
        "① zip 파일을 마우스 오른쪽 클릭합니다.",
        '② "여기에 압축 풀기" 또는 "모두 추출"을 선택합니다.',
        "③ 'N플레이스업체추출기' 폴더가 생성됩니다.",
    ]
    for i, step in enumerate(steps):
        c.drawString(22 * mm, y - 25 * mm - i * 13 * mm, step)

    # 경고
    c.setFillColor(HexColor("#fff3cd"))
    c.roundRect(22 * mm, y - 63 * mm, W - 44 * mm, 12 * mm, 2 * mm, fill=1, stroke=0)
    c.setFillColor(HexColor("#856404"))
    c.setFont("Malgun", 10)
    c.drawString(27 * mm, y - 59 * mm, "⚠ 주의: 폴더 안의 파일들을 개별로 이동하지 마세요. 전체 폴더를 함께 유지해야 합니다.")
    y -= 75 * mm

    # STEP 3
    c.setFillColor(LIGHT_GRAY)
    c.roundRect(15 * mm, y - 55 * mm, W - 30 * mm, 55 * mm, 3 * mm, fill=1, stroke=0)
    c.setFillColor(black)
    c.setFont("MalgunBold", 14)
    c.drawString(22 * mm, y - 10 * mm, "STEP 3  실행")
    c.setFont("Malgun", 11)
    c.drawString(22 * mm, y - 25 * mm, "① 'N플레이스업체추출기' 폴더를 열어줍니다.")
    c.drawString(22 * mm, y - 38 * mm, "② N플레이스업체추출기.exe 파일을 더블클릭합니다.")

    c.setFillColor(HexColor("#d4edda"))
    c.roundRect(22 * mm, y - 53 * mm, W - 44 * mm, 12 * mm, 2 * mm, fill=1, stroke=0)
    c.setFillColor(HexColor("#155724"))
    c.setFont("Malgun", 10)
    c.drawString(27 * mm, y - 49 * mm, "✅ 첫 실행 시 Chromium 브라우저가 자동 설치됩니다. (1~2분 소요)")
    y -= 65 * mm

    # Windows 보안 경고
    c.setFillColor(HexColor("#f8d7da"))
    c.roundRect(15 * mm, y - 45 * mm, W - 30 * mm, 45 * mm, 3 * mm, fill=1, stroke=0)
    c.setFillColor(HexColor("#721c24"))
    c.setFont("MalgunBold", 12)
    c.drawString(22 * mm, y - 12 * mm, "⚠ Windows 보안 경고가 뜨는 경우")
    c.setFont("Malgun", 10)
    c.drawString(22 * mm, y - 25 * mm, '"Windows의 PC 보호" 창이 뜨면:')
    c.drawString(22 * mm, y - 37 * mm, '  → "추가 정보" 클릭 → "실행" 버튼 클릭')

    c.showPage()

    # ━━━━━ 3페이지: 사용 방법 ━━━━━
    draw_page_header(c, 3, total_pages)
    draw_page_footer(c)

    y = H - 35 * mm

    c.setFillColor(black)
    c.setFont("MalgunBold", 20)
    c.drawString(15 * mm, y, "2. 사용 방법")
    y -= 15 * mm

    # 모드 선택
    c.setFillColor(GREEN)
    c.roundRect(15 * mm, y - 50 * mm, W - 30 * mm, 50 * mm, 3 * mm, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("MalgunBold", 14)
    c.drawString(22 * mm, y - 12 * mm, "① 추출 방법 선택")
    c.setFont("Malgun", 11)
    c.drawString(22 * mm, y - 27 * mm, "place : 네이버 플레이스 업체 목록에서 수집 (추천)")
    c.drawString(22 * mm, y - 40 * mm, "blog  : 네이버 블로그 최신순 포스트에서 수집")
    y -= 58 * mm

    # 지역/카테고리
    c.setFillColor(LIGHT_GRAY)
    c.roundRect(15 * mm, y - 60 * mm, W - 30 * mm, 60 * mm, 3 * mm, fill=1, stroke=0)
    c.setFillColor(black)
    c.setFont("MalgunBold", 14)
    c.drawString(22 * mm, y - 12 * mm, "② 지역 · 카테고리 · 갯수 선택")
    c.setFont("Malgun", 11)
    items = [
        "시/도 드롭다운에서 시/도 선택 → 상세지역 자동 변경",
        "대분류 드롭다운에서 업종 선택 → 카테고리 자동 변경",
        "수집 갯수: 10, 20, 30, 50, 100, 150, 200 중 선택",
        "직접 입력도 가능 (최대 200건)",
    ]
    for i, item in enumerate(items):
        c.drawString(22 * mm, y - 27 * mm - i * 10 * mm, f"• {item}")
    y -= 68 * mm

    # 크롤링 시작
    c.setFillColor(LIGHT_GRAY)
    c.roundRect(15 * mm, y - 45 * mm, W - 30 * mm, 45 * mm, 3 * mm, fill=1, stroke=0)
    c.setFillColor(black)
    c.setFont("MalgunBold", 14)
    c.drawString(22 * mm, y - 12 * mm, "③ 크롤링 시작")
    c.setFont("Malgun", 11)
    c.drawString(22 * mm, y - 27 * mm, "• '크롤링 시작' 버튼 클릭 → 자동으로 수집 시작")
    c.drawString(22 * mm, y - 39 * mm, "• 진행률과 실시간 로그가 화면에 표시됩니다.")
    y -= 53 * mm

    # 엑셀 다운로드
    c.setFillColor(HexColor("#d4edda"))
    c.roundRect(15 * mm, y - 40 * mm, W - 30 * mm, 40 * mm, 3 * mm, fill=1, stroke=0)
    c.setFillColor(HexColor("#155724"))
    c.setFont("MalgunBold", 14)
    c.drawString(22 * mm, y - 12 * mm, "④ 엑셀 다운로드")
    c.setFont("Malgun", 11)
    c.drawString(22 * mm, y - 27 * mm, "• 완료 후 '엑셀 다운로드' 버튼 클릭")
    c.drawString(22 * mm, y - 39 * mm, "• 저장 위치를 선택하면 .xlsx 파일이 생성됩니다.")

    c.showPage()

    # ━━━━━ 4페이지: 추출 항목 설명 ━━━━━
    draw_page_header(c, 4, total_pages)
    draw_page_footer(c)

    y = H - 35 * mm

    c.setFillColor(black)
    c.setFont("MalgunBold", 20)
    c.drawString(15 * mm, y, "3. 추출되는 항목")
    y -= 12 * mm

    # 테이블
    headers = ["항목", "설명", "수집률"]
    rows = [
        ["업체명", "네이버 플레이스에 등록된 상호명", "100%"],
        ["대표전화", "업체 대표 전화번호", "90~100%"],
        ["개인번호(010)", "블로그/홈페이지에서 발견된 010 번호", "5~10%"],
        ["이메일", "홈페이지/블로그/스마트스토어에서 추출", "5~15%"],
        ["네이버 아이디", "공식 블로그 URL에서 추출 (=네이버 메일)", "50~60%"],
        ["주소", "사업장 주소", "90~100%"],
        ["카테고리", "업종 분류", "90%"],
        ["블로그 URL", "공식 네이버 블로그 주소", "50~60%"],
        ["홈페이지 URL", "업체 홈페이지 주소", "20~30%"],
    ]

    col_widths = [35 * mm, 80 * mm, 20 * mm]
    table_x = 15 * mm
    row_h = 9 * mm

    # 헤더
    y -= 8 * mm
    c.setFillColor(GREEN)
    c.rect(table_x, y - row_h, sum(col_widths) + 20 * mm, row_h, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("MalgunBold", 10)
    x = table_x + 5 * mm
    for header, w in zip(headers, col_widths):
        c.drawString(x, y - row_h + 3 * mm, header)
        x += w + 5 * mm

    # 데이터
    for i, row in enumerate(rows):
        ry = y - (i + 2) * row_h
        bg = LIGHT_GRAY if i % 2 == 0 else white
        c.setFillColor(bg)
        c.rect(table_x, ry, sum(col_widths) + 20 * mm, row_h, fill=1, stroke=0)
        c.setFillColor(black)
        c.setFont("Malgun", 9)
        x = table_x + 5 * mm
        for val, w in zip(row, col_widths):
            c.drawString(x, ry + 3 * mm, val)
            x += w + 5 * mm

    y -= (len(rows) + 3) * row_h

    # 팁
    c.setFillColor(HexColor("#cce5ff"))
    c.roundRect(15 * mm, y - 50 * mm, W - 30 * mm, 50 * mm, 3 * mm, fill=1, stroke=0)
    c.setFillColor(HexColor("#004085"))
    c.setFont("MalgunBold", 12)
    c.drawString(22 * mm, y - 14 * mm, "💡 활용 팁")
    c.setFont("Malgun", 10)
    tips = [
        "• 네이버 아이디 = 네이버 메일 주소 (아이디@naver.com)",
        "• place 모드가 가장 정확한 데이터를 제공합니다.",
        "• 50건 이상 수집해야 광고 항목을 지나 실제 업체가 나옵니다.",
        "• 크롤링 중 중단해도 수집된 데이터는 저장됩니다.",
    ]
    for i, tip in enumerate(tips):
        c.drawString(22 * mm, y - 28 * mm - i * 7 * mm, tip)

    c.showPage()

    # ━━━━━ 5페이지: 문제 해결 ━━━━━
    draw_page_header(c, 5, total_pages)
    draw_page_footer(c)

    y = H - 35 * mm

    c.setFillColor(black)
    c.setFont("MalgunBold", 20)
    c.drawString(15 * mm, y, "4. 문제 해결 (FAQ)")
    y -= 15 * mm

    faqs = [
        ("Q. 실행하면 바로 꺼져요", [
            "폴더 안의 파일을 개별로 옮기지 않았는지 확인하세요.",
            "전체 폴더를 유지한 상태에서 exe를 실행해야 합니다.",
        ]),
        ("Q. '브라우저 설치 실패' 오류가 나요", [
            "인터넷 연결을 확인하세요.",
            "첫 실행 시 Chromium 브라우저를 자동 다운로드합니다.",
            "방화벽이 차단할 수 있으니 일시적으로 해제해 보세요.",
        ]),
        ("Q. 검색 결과가 0건이에요", [
            "네이버 맵에서 해당 지역+카테고리로 직접 검색해 보세요.",
            "실제로 등록된 업체가 없는 조합일 수 있습니다.",
        ]),
        ("Q. 크롤링 속도가 너무 느려요", [
            "차단 방지를 위해 의도적으로 딜레이를 넣고 있습니다.",
            "50건 기준 약 5~7분이 정상 속도입니다.",
        ]),
        ("Q. 백신(안티바이러스)이 차단해요", [
            "PyInstaller로 빌드한 exe는 오탐이 발생할 수 있습니다.",
            "백신에서 'N플레이스업체추출기' 폴더를 예외 처리하세요.",
        ]),
    ]

    for q, answers in faqs:
        c.setFillColor(HexColor("#e9ecef"))
        ans_height = 10 * mm + len(answers) * 7 * mm
        c.roundRect(15 * mm, y - ans_height, W - 30 * mm, ans_height, 3 * mm, fill=1, stroke=0)

        c.setFillColor(black)
        c.setFont("MalgunBold", 11)
        c.drawString(22 * mm, y - 9 * mm, q)

        c.setFillColor(GRAY)
        c.setFont("Malgun", 10)
        for i, a in enumerate(answers):
            c.drawString(27 * mm, y - 18 * mm - i * 7 * mm, f"→ {a}")

        y -= ans_height + 5 * mm

    c.save()
    print(f"PDF 생성 완료: {OUTPUT}")


if __name__ == "__main__":
    build_pdf()
