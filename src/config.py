# src/config.py
import os


class Config:
    microsoft_app_id: str
    microsoft_app_password: str
    cosmos_endpoint: str
    cosmos_key: str
    cosmos_database: str
    graph_tenant_id: str
    graph_client_id: str
    graph_client_secret: str
    graph_notification_url: str
    port: int
    azure_openai_endpoint: str
    azure_openai_key: str
    azure_openai_deployment: str
    azure_openai_embedding_deployment: str
    azure_search_endpoint: str
    azure_search_key: str
    azure_search_index: str

    def __init__(self) -> None:
        self.microsoft_app_id = os.environ["MICROSOFT_APP_ID"]
        self.microsoft_app_password = os.environ["MICROSOFT_APP_PASSWORD"]
        self.cosmos_endpoint = os.environ["AZURE_COSMOS_ENDPOINT"]
        self.cosmos_key = os.environ["AZURE_COSMOS_KEY"]
        self.cosmos_database = os.environ.get("COSMOS_DATABASE", "meeting_db")
        self.graph_tenant_id = os.environ["GRAPH_TENANT_ID"]
        self.graph_client_id = os.environ["GRAPH_CLIENT_ID"]
        self.graph_client_secret = os.environ["GRAPH_CLIENT_SECRET"]
        self.graph_notification_url = os.environ["GRAPH_NOTIFICATION_URL"]
        self.port = int(os.environ.get("PORT", "3978"))
        self.azure_openai_endpoint = os.environ["AZURE_OPENAI_ENDPOINT"]
        self.azure_openai_key = os.environ["AZURE_OPENAI_KEY"]
        self.azure_openai_deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
        self.azure_openai_embedding_deployment = os.environ.get(
            "AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small"
        )
        self.azure_search_endpoint = os.environ["AZURE_SEARCH_ENDPOINT"]
        self.azure_search_key = os.environ["AZURE_SEARCH_KEY"]
        self.azure_search_index = os.environ.get("AZURE_SEARCH_INDEX", "documents")
