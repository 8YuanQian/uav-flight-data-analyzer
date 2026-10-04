def build_context(information):
    context = ""
    for index,item in enumerate(information):
        context += f"{index+1}. {item['content']} 信息来源:{item['source']} 余弦距离:{item['distance']}\n"
    return context
