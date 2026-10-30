from __future__ import annotations

from .base import PromptTemplate

# For selecting from a list of options with a single word answer
SINGLE_WORD_CHOICE = PromptTemplate(
    template="Look at this screenshot of {context}. Which {item} is currently selected or highlighted? Answer with just a single word: {choices}.",
    required={"context", "item", "choices"},
)

# For settings panels with extra instructions
SETTINGS_SELECTION = PromptTemplate(
    template="Look at this screenshot of {app_name} {settings_section}. Which {item_type} is currently selected or highlighted? Answer with just one word: {choices}. {extra_instructions}",
    required={"app_name", "settings_section", "item_type", "choices", "extra_instructions"},
)

# For simple selections without "Look at this screenshot" preamble
SIMPLE_SELECTION = PromptTemplate(
    template="Which {item} is currently selected or highlighted? Answer with just a single word: {choices}. {extra_instructions}",
    required={"item", "choices", "extra_instructions"},
)
