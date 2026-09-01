from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from openai import OpenAI
from pydantic import BaseModel, ConfigDict

if __package__ in (None, ""):
    project_root = Path(__file__).resolve().parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from judge_config import JudgeConfig, ModelProvider
    from scorer.checkpoints import Checkpoint, NLBlock
    from scorer.prompt import NL_CHECKPOINT_GENERATION_PROMPT
else:
    from .judge_config import JudgeConfig, ModelProvider
    from .scorer.checkpoints import Checkpoint, NLBlock
    from .scorer.prompt import NL_CHECKPOINT_GENERATION_PROMPT


# ============================================================
# Structured output returned by the judge
# ============================================================

class CheckpointOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    premises: list[str]
    goal: list[str]


class NLBlockOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    previous_checkpoint: CheckpointOutput
    arguments: list[str]
    next_checkpoint: CheckpointOutput


class NLBlocksOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    blocks: list[NLBlockOutput]


# ============================================================
# Judge Model
# ============================================================

class JudgeModel:

    def __init__(self, config: JudgeConfig):
        self.config = config
        self._hf_model = None
        self._hf_tokenizer = None

    def generate_nl_blocks(self, theorem_statement: str, natural_language_proof: str) -> list[NLBlock]:
        prompt = self._build_prompt(theorem_statement, natural_language_proof)

        match self.config.provider:
            case ModelProvider.OPENAI:
                output = self._run_openai(prompt)
            case ModelProvider.ANTHROPIC:
                output = self._run_anthropic(prompt)
            case ModelProvider.DEEPSEEK:
                output = self._run_deepseek(prompt)
            case ModelProvider.HUGGINGFACE | ModelProvider.LOCAL:
                output = self._run_huggingface(prompt)
            case _:
                raise ValueError(f"Unsupported model provider: {self.config.provider}")

        blocks = self._convert_to_nl_blocks(output)
        self._validate_transition_consistency(blocks)
        return blocks

    def _build_prompt(self, theorem_statement: str, natural_language_proof: str) -> str:
        return NL_CHECKPOINT_GENERATION_PROMPT.replace("{THEOREM_STATEMENT}", theorem_statement).replace("{NATURAL_LANGUAGE_PROOF}", natural_language_proof)

    def _get_key(self, key: Any, name: str) -> str:
        if key is None:
            raise ValueError(f"{name} is not configured.")
        return key.get_secret_value()

    # ========================================================
    # OpenAI
    # ========================================================

    def _run_openai(self, prompt: str) -> NLBlocksOutput:
        api_key = self._get_key(self.config.api_keys.openai_api_key, "OpenAI API key")
        client = OpenAI(api_key=api_key)

        response = client.responses.create(
            model=self.config.model_name,
            input=prompt,
            max_output_tokens=self.config.generation.max_tokens,
            temperature=self.config.generation.temperature,
            top_p=self.config.generation.top_p,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "nl_proof_blocks",
                    "schema": NLBlocksOutput.model_json_schema(),
                    "strict": True,
                }
            },
        )

        return NLBlocksOutput.model_validate_json(response.output_text)

    # ========================================================
    # Anthropic
    # ========================================================

    def _run_anthropic(self, prompt: str) -> NLBlocksOutput:
        import anthropic

        api_key = self._get_key(self.config.api_keys.anthropic_api_key, "Anthropic API key")
        client = anthropic.Anthropic(api_key=api_key)

        tool = {
            "name": "return_nl_proof_blocks",
            "description": "Return the reconstructed natural-language proof blocks.",
            "input_schema": NLBlocksOutput.model_json_schema(),
        }

        response = client.messages.create(
            model=self.config.model_name,
            max_tokens=self.config.generation.max_tokens,
            temperature=self.config.generation.temperature,
            top_p=self.config.generation.top_p,
            messages=[{"role": "user", "content": prompt}],
            tools=[tool],
            tool_choice={"type": "tool", "name": "return_nl_proof_blocks"},
        )

        for content in response.content:
            if content.type == "tool_use" and content.name == "return_nl_proof_blocks":
                return NLBlocksOutput.model_validate(content.input)

        raise RuntimeError("Anthropic model did not return proof blocks.")

    # ========================================================
    # DeepSeek
    # ========================================================

    def _run_deepseek(self, prompt: str) -> NLBlocksOutput:
        api_key = self._get_key(self.config.api_keys.deepseek_api_key, "DeepSeek API key")
        client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

        response = client.responses.create(
            model=self.config.model_name,
            input=prompt,
            max_output_tokens=self.config.generation.max_tokens,
            temperature=self.config.generation.temperature,
            top_p=self.config.generation.top_p,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "nl_proof_blocks",
                    "schema": NLBlocksOutput.model_json_schema(),
                }
            },
        )

        return NLBlocksOutput.model_validate_json(response.output_text)

    # ========================================================
    # Hugging Face / Local
    # ========================================================

    def _load_huggingface_model(self) -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

        env = self.config.huggingface_environment

        if env is None:
            raise ValueError("huggingface_environment must be provided for Hugging Face or local models.")

        if env.load_in_4bit and env.load_in_8bit:
            raise ValueError("load_in_4bit and load_in_8bit cannot both be True.")

        token = self.config.api_keys.huggingface_token
        token = token.get_secret_value() if token is not None else None

        dtype_map = {
            "auto": "auto",
            "float32": torch.float32,
            "float16": torch.float16,
            "bfloat16": torch.bfloat16,
        }

        quantization_config = None

        if env.load_in_4bit:
            quantization_config = BitsAndBytesConfig(load_in_4bit=True)

        if env.load_in_8bit:
            quantization_config = BitsAndBytesConfig(load_in_8bit=True)

        self._hf_tokenizer = AutoTokenizer.from_pretrained(
            self.config.model_name,
            token=token,
            cache_dir=env.cache_dir,
            trust_remote_code=env.trust_remote_code,
        )

        self._hf_model = AutoModelForCausalLM.from_pretrained(
            self.config.model_name,
            token=token,
            cache_dir=env.cache_dir,
            trust_remote_code=env.trust_remote_code,
            device_map=env.device_map,
            dtype=dtype_map[env.dtype],
            quantization_config=quantization_config,
        )

    def _run_huggingface(self, prompt: str) -> NLBlocksOutput:
        import torch

        if self._hf_model is None or self._hf_tokenizer is None:
            self._load_huggingface_model()

        env = self.config.huggingface_environment
        generation = self.config.generation

        messages = [{"role": "user", "content": prompt}]

        inputs = self._hf_tokenizer.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_tensors="pt",
            return_dict=True,
            truncation=env.max_model_length is not None,
            max_length=env.max_model_length,
        )

        inputs = {name: tensor.to(self._hf_model.device) for name, tensor in inputs.items()}

        generation_arguments = {
            "max_new_tokens": generation.max_tokens,
            "do_sample": generation.temperature > 0,
        }

        if generation.temperature > 0:
            generation_arguments["temperature"] = generation.temperature
            generation_arguments["top_p"] = generation.top_p

        with torch.no_grad():
            output = self._hf_model.generate(**inputs, **generation_arguments)

        generated_tokens = output[0][inputs["input_ids"].shape[-1]:]
        text = self._hf_tokenizer.decode(generated_tokens, skip_special_tokens=True)

        return NLBlocksOutput.model_validate(self._parse_json(text))

    # ========================================================
    # Parsing
    # ========================================================

    @staticmethod
    def _parse_json(text: str) -> dict:
        text = text.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

        try:
            return json.loads(text)
        except json.JSONDecodeError as error:
            raise ValueError(f"Judge model returned invalid JSON:\n{text}") from error

    # ========================================================
    # Convert Pydantic output -> your dataclasses
    # ========================================================

    @staticmethod
    def _convert_checkpoint(checkpoint: CheckpointOutput) -> Checkpoint:
        return Checkpoint(premises=checkpoint.premises, goal=checkpoint.goal)

    @classmethod
    def _convert_to_nl_blocks(cls, output: NLBlocksOutput) -> list[NLBlock]:
        return [
            NLBlock(
                previous_checkpoint=cls._convert_checkpoint(block.previous_checkpoint),
                arguments=block.arguments,
                next_checkpoint=cls._convert_checkpoint(block.next_checkpoint),
            )
            for block in output.blocks
        ]

    # ========================================================
    # Verify C_i -> A_i -> C_i+1 consistency
    # ========================================================

    @staticmethod
    def _validate_transition_consistency(blocks: list[NLBlock]) -> None:
        for i in range(len(blocks) - 1):
            if blocks[i].next_checkpoint != blocks[i + 1].previous_checkpoint:
                raise ValueError(f"Inconsistent proof blocks: block {i}.next_checkpoint != block {i + 1}.previous_checkpoint")