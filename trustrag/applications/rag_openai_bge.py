#!/usr/bin/env python
# -*- coding:utf-8 _*-
"""
@author:quincy qiang
@license: Apache Licence
@file: RagApplication.py
@time: 2024/05/20
@contact: yanqiangmiffy@gamil.com
"""
import os
import loguru
from api.apps.core.rewrite.views import rewrite
from trustrag.modules.citation.match_citation import MatchCitation
from trustrag.modules.document.common_parser import CommonParser
from trustrag.modules.generator.chat import DeepSeekChat
from trustrag.modules.generator.chat import GptTurbo, GPT4_DMXAPI
from trustrag.modules.generator.llm import PROMPT_TEMPLATE
from trustrag.modules.rewriter.llm_rewriter import LLMRewriter
from trustrag.modules.judger.llm_judger import LLMJudger
from trustrag.modules.reranker.bge_reranker import BgeReranker
from trustrag.modules.retrieval.dense_retriever import DenseRetriever
from trustrag.modules.document.chunk import TextChunker
from trustrag.modules.retrieval.embedding import FlagModelEmbedding
from  trustrag.modules.retrieval.web_retriever import DuckduckSearcher
class ApplicationConfig():
    def __init__(self):
        self.retriever_config = None
        self.rerank_config = None


class RagApplication():
    def __init__(self, config):
        self.config = config
        self.parser = CommonParser()
        self.embedding_generator = FlagModelEmbedding(self.config.retriever_config.model_name_or_path)
        self.retriever = DenseRetriever(self.config.retriever_config,self.embedding_generator)
        self.reranker = BgeReranker(self.config.rerank_config)
        # self.llm = DeepSeekChat(key=self.config.key)
        self.llm = GPT4_DMXAPI(key=self.config.key)
        self.system_prompt = "你是一个可信可靠的问答助手。"
        self.llm_rewriter = LLMRewriter(api_key=self.config.key)
        self.llm_judger = LLMJudger(api_key=self.config.key)
        self.mc = MatchCitation()
        self.tc=TextChunker()
        self.web_searcher=DuckduckSearcher(proxy=None, timeout=20)
    def init_vector_store(self):
        """
        """
        print("init_vector_store ... ")
        all_paragraphs = []
        all_chunks = []
        for filename in os.listdir(self.config.docs_path):
            file_path = os.path.join(self.config.docs_path, filename)
            try:
                paragraphs=self.parser.parse(file_path)
                all_paragraphs.append(paragraphs)
            except:
                pass
        print("chunking for paragraphs")
        for paragraphs in all_paragraphs:
            chunks=self.tc.get_chunks(paragraphs, 256)
            all_chunks.extend(chunks)
        self.retriever.build_from_texts(all_chunks)
        print("init_vector_store done! ")
        self.retriever.save_index(self.config.retriever_config.index_path)

    def load_vector_store(self):
        self.retriever.load_index(self.config.retriever_config.index_path)

    def add_document(self, file_path):
        chunks = self.parser.parse(file_path)
        for chunk in chunks:
            self.retriever.add_text(chunk)
        print("add_document done!")

    def chat(self, question: str = '', top_k: int = 5):
        rewrite_query=self.llm_rewriter.rewrite(question)
        rewrite_query="\n".join(f"{i+1}. {query.strip()};" for i, query in enumerate(rewrite_query.split(";")))
        loguru.logger.info("Query Rewrite Results:"+rewrite_query)
        contents = self.retriever.retrieve(query=question, top_k=top_k)
        contents = self.reranker.rerank(query=question, documents=[content['text'] for content in contents])
        documents=[content['text'] for content in contents]
        labels=self.llm_judger.judge(question,documents=documents)
        loguru.logger.info("Useful Judge Results:")
        for content,label in zip(contents,labels):
            content['label']=label
        loguru.logger.info(contents)


        context_content = ""
        for idx, item in enumerate(contents):
            print(idx+1)
            context_content=context_content+ str(idx + 1)+"."+item['text']+"\n"
        print(context_content)
        user_input=PROMPT_TEMPLATE['RAG_PROMPT_TEMPALTE'].format(question=question, context=context_content)
        loguru.logger.info("User Request：\n"+user_input)

        history = [
            {"role": "user", "content": user_input}
        ]
        result, history = self.llm.chat(system=self.system_prompt, history=history,gen_conf={"temperature": 0.3})
        # result = self.mc.ground_response(
        #     question=question,
        #     response=result,
        #     evidences=[content['text'] for content in contents],
        #     selected_idx=[idx for idx in range(len(contents))],
        #     markdown=True
        # )
        return result, history, contents,rewrite_query
