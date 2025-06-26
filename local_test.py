import asyncio
from datetime import datetime
from openai import AsyncOpenAI
from src.config import settings
from graphiti_core import Graphiti
from graphiti_core.llm_client import OpenAIClient
from graphiti_core.nodes import EpisodeType
from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
from graphiti_core.llm_client.config import LLMConfig
async def main():
    # knowledge_graph = KnowledgeGraph()
    # await knowledge_graph.init_knowledge_graph()
    
    # await knowledge_graph.graphiti.remove_episode(
    #     episode_uuid="9ce12012-5751-4692-ad4d-991a3ce11bc5"
    # )
    # await knowledge_graph.graphiti.remove_episode(
    #     episode_uuid="13bf5d96-5756-4d5d-89ba-6758ae04fb13"
    # )
    # await knowledge_graph.close_knowledge_graph()
    # openai_client = AsyncOpenAI(
    #     api_key=settings.OPENAI_API_KEY,
    #     base_url="https://ark.cn-beijing.volces.com/api/v3",
    # )

    # llm_config = LLMConfig(
    #             model=settings.OPENAI_MODEL,
    #             api_key=settings.OPENAI_API_KEY,
    #             base_url="https://ark.cn-beijing.volces.com/api/v3",
    #             small_model=settings.OPENAI_MODEL,
    #             temperature=0.7
    #             # max_tokens=32768
    #         )
    # graphiti = Graphiti(
    #     "bolt://14.103.186.222:7687",
    #     "neo4j",
    #     "DCCcloud2024",
    #     llm_client=OpenAIClient(
    #         client=openai_client,
    #         config=llm_config
    #     ),
    #     embedder=OpenAIEmbedder(
    #         config=OpenAIEmbedderConfig(
    #             embedding_model="ep-20250326160816-hpj2z",
    #             api_key=settings.OPENAI_API_KEY,
    #             base_url="https://ark.cn-beijing.volces.com/api/v3"
    #         ),
    #         client=openai_client
    #     ),
    #     # Optional: Configure the OpenAI cross encoder with Azure OpenAI
    #     cross_encoder=OpenAIRerankerClient(
    #         client=openai_client,
    #         config=llm_config
    #     )
    # )
    # try:
    #     # Initialize the graph database with graphiti's indices. This only needs to be done once.
    #     await graphiti.build_indices_and_constraints()
    #     await graphiti.add_episode(
    #         name="test",
    #         episode_body="test",
    #         source=EpisodeType.text,
    #         reference_time=datetime.now(),
    #         source_description='game_analysis'
    #     )
    #     # Additional code will go here
    # except Exception as e:
    #     print(f"Error: {e}")
    # finally:
    #     # Close the connection
    #     await graphiti.close()
    #     print('\nConnection closed')
        # import uuid
    import json
    import os
    from pathlib import Path
    from langchain_core.documents import Document
    from src.utils.custom_embedding import DoubaoEmbeddings
    from src.agents.memory.open_search_memory_store import OpenSearchMemoryStore
    from src.store.message_store import ChatHistoryStore
    
    chat_history_store = ChatHistoryStore()
    chat_history = chat_history_store.get_chat_history(chat_history_id="123456")
    print(chat_history)
    # store = OpenSearchMemoryStore(index_name="mindmap_index", embedding=DoubaoEmbeddings(), user_id="jinming")
    # store = OpenSearchMemoryStore(index_name="matman_game_info", embedding=DoubaoEmbeddings(), user_id="jinming")
    # document = Document(
    #     id="03111eb8-5792-4563-a1e6-12b8f28b2b70",
    #     page_content="王者农药",
    #     metadata={"source": "https://example.com", "game_name": "test1", "user_name": "kevin"}
    # )
    # document1 = Document(
    #     id="03111eb8-5792-4563-a1e6-12b8f28b2b71",
    #     page_content="王者荣耀",
    #     metadata={"source": "https://example2.com", "game_name": "test2", "user_name": "kevi2"}
    # )
    # store.add_documents([document, document1])
    # search_result = store.get_game_info_by_id("cdec8c6f-0cb4-4ce2-af4f-68f99ba82642")
    # print(search_result)
    # game_info = store.get_game_info_by_id("ca371a85-5b3f-4f4f-86b1-c137d3daaf4e")
    # # # game_info.metadata["game_name"] = "幸存者群岛"
    # # game_info.page_content = game_info.metadata["game_name"]
    # # search_result.metadata["user_id"] = "jinming"
    # # store.add_documents([search_result])
    # mindmap_store = MindmapStore()
    # mindmap = mindmap_store.get_mindmap_by_id("z4FAGpcBCw684Lm5bYpM")
    # # mindmap = mindmap_store.client.client.get(index=mindmap_store.index_name, id="z4FAGpcBCw684Lm5bYpM")["_source"]["doc"]["mindmap"]
    # # mindmap_store.client.client.delete(index=mindmap_store.index_name, id="z4FAGpcBCw684Lm5bYpM")   
    # # mindmap_store.client.client.create(index=mindmap_store.index_name, id="z4FAGpcBCw684Lm5bYpM", body={"username": "jinming", "game_name": "幸存者岛屿", "mindmap": mindmap})
    # print(mindmap)
    # print(search_result[0].metadata)
    # game_info = store.get_game_info_by_id(search_result[0].id)
    # print(game_info.metadata)
    # store.delete(ids=[search_result[1].id])
    # store.delete(ids=[search_result[2].id])
    # search_result = store.similarity_search(query="幸存者", k=10)
    # print(search_result[0].metadata)
    # search_result[0].metadata["game_creative_report"]["reference_ideas"] = []

    # image_folder = Path("local_image")
    # for image_file in image_folder.glob("*.jpg"):
    #     print(f"Processing image: {image_file}")
    #     search_result[0].metadata["game_creative_report"]["reference_ideas"].append(
    #         {
    #             "image_path": f"Public/03111eb8-5792-4563-a1e6-12b8f28b2b70/{Path(image_file).name}",
    #         }
    #     )
    # store.add_documents(search_result)
    # 在这里处理每个图片文件
    # creative_ideas_obj = json.loads(search_result[0].metadata["game_creative_report"]["creative_ideas"])
    # print(creative_ideas_obj)
    # store.delete(ids=["f5d936ae-3b16-4a69-9ca1-8cedc09b214b"])
    # store.delete(ids=["03111eb8-5792-4563-a1e6-12b8f28b2b71"])

    # search_result[0].metadata["game_creative_report"] = {
    #     "selling_points": json.loads(search_result[0].metadata["game_creative_report"]["selling_points"]),
    #     "creative_ideas": json.loads(search_result[0].metadata["game_creative_report"]["creative_ideas"])
    # }
    # store.add_documents(search_result)

if __name__ == '__main__':
    asyncio.run(main())