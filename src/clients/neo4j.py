from functools import lru_cache

from neo4j import Driver, GraphDatabase

from src.config import get_settings


@lru_cache
def get_neo4j() -> Driver:
    s = get_settings()
    return GraphDatabase.driver(s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password))
