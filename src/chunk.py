def chunk_content(content, chunk_size=500, overlap=50):
    """
    将内容分割成指定大小的块。

    参数:
    content (str): 要分割的内容。
    chunk_size (int): 每个块的最大字符数。
    overlap (int): 块之间的重叠字符数。

    返回:
    list: 包含内容块的列表。
    """
    chunks = []
    for i in range(0, len(content), chunk_size - overlap):
        chunks.append(content[i:i + chunk_size])
    return chunks
                   