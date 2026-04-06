from pydantic import BaseModel
from typing import Optional


class Business(BaseModel):
    """네이버 스마트플레이스 업체 데이터 모델"""
    name: str                              # 업체명
    phone: Optional[str] = None            # 대표 전화번호
    personal_phone: Optional[str] = None   # 개인번호 (010, 블로그/홈페이지에서 추출)
    email: Optional[str] = None            # 이메일 (홈페이지/블로그에서 추출)
    naver_id: Optional[str] = None         # 네이버 아이디 (블로그 URL에서 추출)
    address: Optional[str] = None          # 주소
    category: Optional[str] = None         # 카테고리
    blog_url: Optional[str] = None         # 공식 블로그 URL
    homepage_url: Optional[str] = None     # 홈페이지 URL
    place_id: Optional[str] = None         # 네이버 Place ID (중복 방지용)
