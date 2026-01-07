import re
from datetime import datetime
import hashlib

def find_datetime_from_str(text: str) -> str:
    """
    从字符串中寻找如下格式的日期，并以 %Y-%m-%d %H:%M:%S 格式的字符串返回
    %Y-%m-%d %H:%M:%S
    %Y-%m-%d %H:%M
    %Y-%m-%d
    %H:%M:%S
    """
    if not text:
        return None
    
    patterns = [
        (r'(\d{4}-\d{1,2}-\d{1,2}\s+\d{1,2}:\d{1,2}:\d{1,2})', '%Y-%m-%d %H:%M:%S'),
        (r'(\d{4}-\d{1,2}-\d{1,2}\s+\d{1,2}:\d{1,2})', '%Y-%m-%d %H:%M'),
        (r'(\d{4}-\d{1,2}-\d{1,2})', '%Y-%m-%d'),
        (r'(\d{1,2}:\d{1,2}:\d{1,2})', '%H:%M:%S'),
    ]

    for pattern, fmt in patterns:
        match = re.search(pattern, text)
        if match:
            dt_str = match.group(1)
            try:
                dt = datetime.strptime(dt_str, fmt)
                return dt.strftime('%Y-%m-%d %H:%M:%S')
            except ValueError:
                continue
    
    return None

def find_int_from_str(text: str) -> int:
    """
    从字符串中寻找整数，并以整数返回
    """
    if not text:
        return None
    match = re.search(r'\d+', text)
    if match:
        return safe_int(match.group(0))
    return None

def get_flag_name_from_url(url: str) -> str:
    """
    通过图片链接里的图片名称来分析帖子的flag
    """
    if not url:
        return None
    
    flag_name_map = {
        "011.small": "新人贴",
        "hot": "火热",
        "recommend": "推荐",
        "pollsmall": "投票",
        "folder_lock": "关闭的主题",
        "digest": "精华帖",
    }

    img_name = url.split("/")[-1]
    for k in flag_name_map.keys():
        if k in img_name:
            return flag_name_map[k]
    return f"未知标签[{img_name.strip()}]"

def safe_int(text: str) -> int:
    """
    将字符串转换为整数，如果转换失败则返回 None
    """
    try:
        return int(text)
    except ValueError:
        return None

def generate_uuid(str_data: str) -> str:
    """
    生成一个唯一的UUID
    """
    return hashlib.md5(str_data.encode()).hexdigest()