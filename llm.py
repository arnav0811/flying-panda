"""
call_llm (free-text response) and call_llm_json (structured JSON response)
using GPT-4o-mini.
"""

import os
import json
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# cheap output price could switch to gpt5-mini but is $2 worth it?
MODEL = "gpt-4o-mini"


def call_llm(system_prompt, user_prompt, temperature=0.8):
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
    )
    return response.choices[0].message.content


def call_llm_json(system_prompt, user_prompt, temperature=0.8):
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        response_format={"type": "json_object"},
    )
    text = response.choices[0].message.content
    return json.loads(text)
