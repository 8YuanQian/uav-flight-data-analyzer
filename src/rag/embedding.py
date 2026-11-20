from typing import Literal


EmbeddingEncoding = Literal["legacy-unprefixed", "e5-prefixed"]
LEGACY_ENCODING: EmbeddingEncoding = "legacy-unprefixed"
E5_ENCODING: EmbeddingEncoding = "e5-prefixed"
EMBEDDING_ENCODINGS = (LEGACY_ENCODING, E5_ENCODING)


def create_embedding(argument, embedding_model):
    return embedding_model.encode(argument)


def _format_input(text: str, prefix: str, encoding: EmbeddingEncoding) -> str:
    if encoding == E5_ENCODING:
        return prefix + text
    if encoding == LEGACY_ENCODING:
        return text
    raise ValueError(f"不支持的向量编码方式：{encoding}")


def create_query_embedding(query: str, embedding_model, *, encoding: EmbeddingEncoding):
    return embedding_model.encode(_format_input(query, "query: ", encoding))


def create_passage_embeddings(passages: str | list[str], embedding_model,
                              *, encoding: EmbeddingEncoding, **encode_options):
    # 保留单条与批量输入的形状；前缀只进入模型，不写入文档正文。
    if isinstance(passages, str):
        inputs = _format_input(passages, "passage: ", encoding)
    else:
        inputs = [_format_input(text, "passage: ", encoding) for text in passages]
    return embedding_model.encode(inputs, **encode_options)
