from functools import lru_cache

MODEL_NAME = "BAAI/bge-small-en-v1.5"


@lru_cache
def _model():  # type: ignore[no-untyped-def]
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=MODEL_NAME)


def embed(texts: list[str]) -> list[list[float]]:
    return [v.tolist() for v in _model().embed(texts)]
