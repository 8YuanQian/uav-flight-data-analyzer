def save_csv_data(filename, content):
    """将 DataFrame 保存为 CSV 文件。"""
    content.to_csv(filename)
