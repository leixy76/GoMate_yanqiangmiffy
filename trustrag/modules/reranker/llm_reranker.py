#!/usr/bin/env python
# -*- coding:utf-8 _*-
"""
@author:jun yang
@license: Apache Licence
@file: main.py
@time: 2025/03/11
@contact: oliveryoung200211@gamil.com
@software: PyCharm
@description: coding..
"""
import os

os.environ["TOKENIZERS_PARALLELISM"] = "false"
from typing import Any, List

import torch
from torch.utils.data import DataLoader, Dataset
from transformers import (
    AutoConfig,
    AutoModelForCausalLM,
    AutoTokenizer,
    T5ForConditionalGeneration,
    T5Tokenizer,
)

from trustrag.modules.reranker.base import BaseReranker

setwise_likelihood = """
你是一个专业的搜索算法助手，可以根据找出与查询最相关的段落。
以下是{num}段文字，每段都用字母标识符依次表示。你需要根据与查询的相关性找出最相关的段落。
查询内容为：<查询>{query}</查询>
段落内容为：<段落>{docs}</段落>
根据与搜索查询相关性找出上述{num}段文字中最相关的段落。你应该只输出最相关段落的标识符。只回复最终结果，不要说任何其他话。请注意，如果有多个段落与查询相关度相同，则随机选择一个。
"""

pointwise_query_generation = """
你是一个专业的搜索算法助手，可以根据段落找出最相关的查询。
以下是一个段落，请基于该段落写出对应的查询。
段落内容为：<段落>{doc}</段落>
"""

pointwise_relevance_generation = """
你是一个专业的搜索算法助手，可以判断查询和段落间的相关性。
以下是一个查询和一个段落，这个段落是否回答了该查询？
查询内容为：<查询>{query}</查询>
段落内容为：<段落>{doc}</段落>
请只回答"Yes"或"No"。
"""


class LLMRerankerConfig:
    """
    Configuration class for setting up a LLM reranker.

    Attributes:
        model_name_or_path (str): Path or model identifier for the pretrained model from Hugging Face's model hub.
        device (str): Device to load the model onto ('cuda' or 'cpu').
        api_key (str): API key for the reranker service.
        url (str): URL for the reranker service.
    """

    def __init__(
        self, model_name_or_path="Qwen2.5-7B-Instruct", api_key=None, url=None
    ):
        self.model_name_or_path = model_name_or_path
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.api_key = api_key
        self.url = url

    def log_config(self):
        # Log the current configuration settings
        return f"""
        LLMRerankerConfig:
            Model Name or Path: {self.model_name_or_path}
            Device: {self.device}
            URL: {self.url}
            API Key: {'*' * 8 if self.api_key else 'Not Set'}
        """


class SetWiseReranker(BaseReranker):
    """
    A reranker that utilizes a LLM to rerank a list of documents based on their relevance to a given query.
    """

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.CHARACTERS = [
            "A",
            "B",
            "C",
            "D",
            "E",
            "F",
            "G",
            "H",
            "I",
            "J",
            "K",
            "L",
            "M",
            "N",
            "O",
            "P",
            "Q",
            "R",
            "S",
            "T",
        ]
        self.rerank_tokenizer = AutoTokenizer.from_pretrained(config.model_name_or_path)
        self.rerank_model = (
            AutoModelForCausalLM.from_pretrained(config.model_name_or_path)
            .half()
            .to(config.device)
            .eval()
        )
        self.device = config.device
        self.decoder_input_ids = self.rerank_tokenizer.encode(
            "<pad> 最相关的段落是：", return_tensors="pt", add_special_tokens=False
        ).to(self.device)
        self.target_token_ids = self.rerank_tokenizer.batch_encode_plus(
            [
                f"<pad> 最相关的段落是：{self.CHARACTERS[i]}"
                for i in range(len(self.CHARACTERS))
            ],
            return_tensors="pt",
            add_special_tokens=False,
            padding=True,
        ).input_ids[:, -1]
        print("Successful load rerank model")

    def rerank(
        self,
        query: str,
        documents: List[str],
        k: int = 5,
        is_sorted: bool = True,
        method: str = "setwise_likelihood",
    ) -> list[dict[str, Any]]:
        # Process input documents for uniqueness and formatting

        if method == "setwise_likelihood":
            indexed_docs = "\n".join(
                [f"{self.CHARACTERS[i]}: {doc}" for i, doc in enumerate(documents)]
            )
            params = {"query": query, "docs": indexed_docs, "num": len(documents)}
            if len(documents) > 20:
                raise ValueError("目前暂不支持超过20条文档排序！")
            input_text = setwise_likelihood.format(**params)
            input_ids = self.rerank_tokenizer(
                input_text, return_tensors="pt"
            ).input_ids.to(self.device)
            # Tokenize and predict relevance scores
            with torch.no_grad():

                logits = self.rerank_model(
                    input_ids=input_ids, decoder_input_ids=self.decoder_input_ids
                ).logits[0][-1]
                distributions = torch.softmax(logits, dim=0)
                scores = distributions[self.target_token_ids[: len(documents)]]

            # Pair documents with their scores, sort by scores in descending order
            if is_sorted:
                ranked_docs = sorted(
                    zip(documents, scores), key=lambda x: x[1], reverse=True
                )
                # Return the top k documents
                top_docs = [
                    {"text": doc, "score": score.item()} for doc, score in ranked_docs
                ]
            else:
                top_docs = [
                    {"text": doc, "score": score.item()}
                    for doc, score in zip(documents, scores)
                ]

            return top_docs
        else:
            raise NotImplementedError(f"{method}未实施！")


class PointWiseReranker(BaseReranker):
    """
    A reranker that utilizes a LLM to rerank a list of documents based on their relevance to a given query.
    """

    def __init__(self, config):
        super().__init__()
        self.config = config
        if AutoConfig.from_pretrained(config.model_name_or_path).model_type == "t5":
            self.rerank_tokenizer = T5Tokenizer.from_pretrained(
                config.model_name_or_path
            )
            self.rerank_model = (
                T5ForConditionalGeneration.from_pretrained(config.model_name_or_path)
                .half()
                .to(config.device)
                .eval()
            )
        else:
            raise NotImplementedError(f"Please use T5 model!")

        self.device = config.device
        self.batch_size = 16
        print("Successful load rerank model")

    def rerank(
        self,
        query: str,
        documents: List[str],
        k: int = 5,
        is_sorted: bool = True,
        method: str = "relevance_generation",
    ) -> list[dict[str, Any]]:
        # Process input documents for uniqueness and formatting
        scores = []
        if method == "relevance_generation":
            yes_id = self.rerank_tokenizer.encode("Yes", add_special_tokens=False)[0]
            no_id = self.rerank_tokenizer.encode("No", add_special_tokens=False)[0]
            data = []
            for doc in documents:
                params = {"query": query, "doc": doc}
                input_text = pointwise_relevance_generation.format(**params)
                inputs = self.rerank_tokenizer(input_text, return_tensors="pt").to(
                    self.device
                )
                decoder_input_ids = torch.Tensor(
                    [self.rerank_tokenizer.pad_token_id]
                ).to(self.device, dtype=torch.long)
                with torch.no_grad():
                    logits = self.rerank_model(
                        input_ids=inputs["input_ids"].repeat(1, 1),
                        attention_mask=inputs["attention_mask"].repeat(1, 1),
                        decoder_input_ids=decoder_input_ids.repeat(1, 1),
                    ).logits
                    yes_scores = logits[:, :, yes_id]
                    no_scores = logits[:, :, no_id]
                    score = torch.cat((yes_scores, no_scores), dim=1)
                    score = torch.nn.functional.softmax(score, dim=1)
                    scores.append(score[:, 0])

        elif method == "query_generation":
            data = []
            for doc in documents:
                params = {"query": query, "doc": doc}
                input_text = pointwise_query_generation.format(**params)
                inputs = self.rerank_tokenizer(input_text, return_tensors="pt").to(
                    self.device
                )
                label = (
                    self.rerank_tokenizer.encode(
                        f"<pad> {query}", return_tensors="pt", add_special_tokens=False
                    )
                    .to(self.device)
                    .repeat(1, 1)
                )
                with torch.no_grad():
                    logits = self.rerank_model(
                        input_ids=inputs["input_ids"].repeat(1, 1),
                        attention_mask=inputs["attention_mask"].repeat(1, 1),
                        labels=label,
                    ).logits

                    loss_fct = torch.nn.CrossEntropyLoss(reduction="none")
                    score = loss_fct(logits.view(-1, logits.size(-1)), label.view(-1))
                    score = -1 * score.view(-1, label.size(-1)).sum(
                        dim=1
                    )  # neg log prob
                    scores.append(score)
        else:
            raise NotImplementedError(f"{method} is not applied!")
        if is_sorted:
            ranked_docs = sorted(
                zip(documents, scores), key=lambda x: x[1], reverse=True
            )
            # Return the top k documents
            top_docs = [
                {"text": doc, "score": score.item()} for doc, score in ranked_docs
            ]
        else:
            top_docs = [
                {"text": doc, "score": score.item()}
                for doc, score in zip(documents, scores)
            ]

        return top_docs
