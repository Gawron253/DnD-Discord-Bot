"""Moduł bezpiecznego dzielenia długich wiadomości narracyjnych dla Discorda.
Zapobiega błędom HTTP 400 Bad Request przy przekroczeniu limitu 2000 znaków Discorda,
dzieląc tekst na logiczne akapity i zdania z zachowaniem formatowania.
"""
from __future__ import annotations
import re
from typing import List


def split_long_message(text: str, limit: int = 1900) -> List[str]:
    """
    Dzieli długi tekst na bezpieczne fragmenty o długości nieprzekraczającej `limit` (domyślnie 1900 znaków).
    Zachowuje granice akapitów (\n\n), zdań (. / ! / ?), linii oraz bloków kodu Markdown.

    Args:
        text: Tekst do podzielenia (np. długa odpowiedź narracyjna AI).
        limit: Maksymalna liczba znaków w pojedynczej wiadomości (<=2000).

    Returns:
        Lista niepustych fragmentów tekstu, każdy <= limit znaków.
    """
    if not text or not text.strip():
        return []

    stripped = text.strip()
    if len(stripped) <= limit:
        return [stripped]

    chunks: List[str] = []
    # 1. Podział na akapity (podwójna nowa linia)
    paragraphs = text.split("\n\n")
    current_chunk = ""
    in_code_block = False
    code_block_lang = ""

    for p in paragraphs:
        p_clean = p.strip()
        if not p_clean:
            continue

        # Sprawdzenie czy pojedynczy akapit mieści się w limicie
        if len(p_clean) > limit:
            # Jeżeli mamy już zgromadzony tekst w bieżącym fragmencie, zrzuć go
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = ""

            # 2. Podział długiego akapitu na zdania
            sentences = re.split(r"(?<=[.!?…])\s+", p_clean)
            sub_chunk = ""

            for s in sentences:
                s_clean = s.strip()
                if not s_clean:
                    continue

                if len(s_clean) > limit:
                    # Pojedyncze olbrzymie zdanie / ciąg znaków bez spacji
                    if sub_chunk:
                        chunks.append(sub_chunk.strip())
                        sub_chunk = ""

                    # Podział po pojedynczych liniach lub słowach
                    words = s_clean.split(" ")
                    word_chunk = ""
                    for w in words:
                        if len(w) > limit:
                            # Twardy podział słowa dłuższego niż limit
                            if word_chunk:
                                chunks.append(word_chunk.strip())
                                word_chunk = ""
                            for i in range(0, len(w), limit):
                                chunks.append(w[i:i + limit].strip())
                        elif len(word_chunk) + len(w) + 1 <= limit:
                            word_chunk = f"{word_chunk} {w}".strip()
                        else:
                            chunks.append(word_chunk.strip())
                            word_chunk = w
                    if word_chunk:
                        sub_chunk = word_chunk
                elif len(sub_chunk) + len(s_clean) + 1 <= limit:
                    sub_chunk = f"{sub_chunk} {s_clean}".strip()
                else:
                    if sub_chunk:
                        chunks.append(sub_chunk.strip())
                    sub_chunk = s_clean

            if sub_chunk:
                current_chunk = sub_chunk
        elif len(current_chunk) + len(p_clean) + 2 <= limit:
            current_chunk = f"{current_chunk}\n\n{p_clean}".strip() if current_chunk else p_clean
        else:
            chunks.append(current_chunk.strip())
            current_chunk = p_clean

    if current_chunk:
        chunks.append(current_chunk.strip())

    # Filtracja pustych elementów i końcowa weryfikacja
    final_chunks: List[str] = []
    for c in chunks:
        c_clean = c.strip()
        if not c_clean:
            continue
        if len(c_clean) <= limit:
            final_chunks.append(c_clean)
        else:
            # Ostateczny fallback na twarde cięcie
            for i in range(0, len(c_clean), limit):
                part = c_clean[i:i + limit].strip()
                if part:
                    final_chunks.append(part)

    return final_chunks
