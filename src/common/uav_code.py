def normalize_uav_code(uav_code: str) -> str:
    # 飞行器编号统一去除首尾空格并转为大写，供写入和查询共同使用。
    # 同一编号的不同大小写形式最终使用同一个数据库唯一值。
    return uav_code.strip().upper()
