"""Gráficos em SVG gerados no servidor.

Sem biblioteca de front-end e sem CDN: o SVG vai inline no HTML, então o painel
funciona offline e carrega instantaneamente. As funções devolvem strings e são
testáveis isoladamente.
"""

from __future__ import annotations

import html
import math
from typing import Any, Iterable, Sequence

from ..money import format_centavos

PALETTE = [
    "#0ea5e9", "#f97316", "#22c55e", "#ef4444", "#a855f7", "#eab308",
    "#14b8a6", "#f43f5e", "#6366f1", "#84cc16", "#ec4899", "#64748b",
]

COR_ENTRADA = "#16a34a"
COR_SAIDA = "#ef4444"


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def compact_brl(centavos: int) -> str:
    """Rótulo curto para eixos: 12_345_00 → ``R$ 12,3 mil``."""
    reais = abs(int(centavos)) / 100
    sinal = "-" if centavos < 0 else ""
    if reais >= 1_000_000:
        return f"{sinal}R$ {reais / 1_000_000:.1f}".replace(".", ",") + " mi"
    if reais >= 1_000:
        return f"{sinal}R$ {reais / 1_000:.1f}".replace(".", ",") + " mil"
    return f"{sinal}R$ {reais:.0f}"


def _nice_max(valor: int) -> int:
    """Arredonda o teto do eixo para um número "bonito"."""
    if valor <= 0:
        return 100_00  # R$ 100,00
    expoente = math.floor(math.log10(valor))
    base = 10 ** expoente
    for multiplo in (1, 2, 2.5, 5, 10):
        if valor <= base * multiplo:
            return int(base * multiplo)
    return int(base * 10)


def bars_series(
    serie: Sequence[dict[str, Any]],
    width: int = 760,
    height: int = 300,
    title: str = "Entradas × saídas por mês",
) -> str:
    """Barras agrupadas (verde = entrou, vermelho = saiu) por mês."""
    if not serie:
        return empty_chart(width, height, "Sem dados para exibir")

    pad_l, pad_r, pad_t, pad_b = 64, 16, 34, 52
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    teto = _nice_max(max(max(s["entradas"], s["saidas"]) for s in serie))

    n = len(serie)
    grupo = plot_w / n
    barra = min(30.0, grupo * 0.32)
    partes: list[str] = [
        f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{esc(title)}" xmlns="http://www.w3.org/2000/svg">',
        f'<text x="{pad_l}" y="20" class="chart-title">{esc(title)}</text>',
    ]

    # linhas de grade + rótulos do eixo Y
    for i in range(5):
        y = pad_t + plot_h - (plot_h * i / 4)
        valor = teto * i / 4
        partes.append(
            f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width - pad_r}" y2="{y:.1f}" class="grid"/>'
            f'<text x="{pad_l - 8}" y="{y + 4:.1f}" class="axis" text-anchor="end">{esc(compact_brl(int(valor)))}</text>'
        )

    for idx, ponto in enumerate(serie):
        centro = pad_l + grupo * idx + grupo / 2
        for offset, chave, cor in ((-barra - 2, "entradas", COR_ENTRADA), (2, "saidas", COR_SAIDA)):
            valor = int(ponto.get(chave) or 0)
            altura = (valor / teto * plot_h) if teto else 0
            x = centro + offset
            y = pad_t + plot_h - altura
            rotulo = format_centavos(valor) if valor else "0,00"
            partes.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{barra:.1f}" height="{max(altura, 0):.1f}" '
                f'rx="3" fill="{cor}" opacity="{0.45 if ponto.get("vazio") else 1}">'
                f'<title>{esc(ponto.get("label", ponto["period"]))} — {esc(chave)}: R$ {esc(rotulo)}</title></rect>'
            )
        partes.append(
            f'<text x="{centro:.1f}" y="{height - pad_b + 20}" class="axis" text-anchor="middle">'
            f'{esc(ponto.get("label") or ponto["period"])}</text>'
        )
        saldo = int(ponto.get("saldo") or 0)
        cor_saldo = COR_ENTRADA if saldo >= 0 else COR_SAIDA
        partes.append(
            f'<text x="{centro:.1f}" y="{height - pad_b + 38}" class="axis-small" '
            f'text-anchor="middle" fill="{cor_saldo}">{esc(compact_brl(saldo))}</text>'
        )

    partes.append(
        f'<line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{width - pad_r}" y2="{pad_t + plot_h}" class="axis-line"/>'
    )
    partes.append("</svg>")
    return "".join(partes)


def hbar(
    itens: Sequence[dict[str, Any]],
    width: int = 720,
    row_h: int = 30,
    title: str = "",
    value_key: str = "total",
    label_key: str = "name",
    color_key: str = "color",
) -> str:
    """Barras horizontais — ranking de categorias/itens."""
    dados = [i for i in itens if int(i.get(value_key) or 0) > 0][:12]
    if not dados:
        return empty_chart(width, 120, "Sem dados para exibir")
    height = len(dados) * row_h + (34 if title else 12)
    pad_l = min(220, int(width * 0.34))
    pad_r = 110
    barra_w = max(40, width - pad_l - pad_r)
    teto = max(int(d.get(value_key) or 0) for d in dados) or 1

    partes = [
        f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="{esc(title)}" '
        f'xmlns="http://www.w3.org/2000/svg">'
    ]
    if title:
        partes.append(f'<text x="8" y="20" class="chart-title">{esc(title)}</text>')

    for idx, item in enumerate(dados):
        y = (34 if title else 12) + idx * row_h
        valor = int(item.get(value_key) or 0)
        largura = max(2.0, valor / teto * barra_w)
        cor = item.get(color_key) or PALETTE[idx % len(PALETTE)]
        partes.append(
            f'<text x="{pad_l - 10}" y="{y + 17}" class="axis" text-anchor="end">'
            f'{esc(str(item.get(label_key) or "")[:28])}</text>'
            f'<rect x="{pad_l}" y="{y + 5}" width="{barra_w}" height="{row_h - 14}" rx="4" class="track"/>'
            f'<rect x="{pad_l}" y="{y + 5}" width="{largura:.1f}" height="{row_h - 14}" rx="4" fill="{esc(cor)}">'
            f'<title>{esc(item.get(label_key))}: R$ {esc(format_centavos(valor))}</title></rect>'
            f'<text x="{pad_l + barra_w + 8}" y="{y + 17}" class="axis">R$ {esc(format_centavos(valor))}</text>'
        )
    partes.append("</svg>")
    return "".join(partes)


def donut(
    fatias: Iterable[dict[str, Any]],
    size: int = 220,
    thickness: int = 34,
    center_label: str = "",
    center_value: str = "",
) -> str:
    """Rosca de participação por categoria."""
    dados = [f for f in fatias if int(f.get("total") or 0) > 0]
    total = sum(int(f.get("total") or 0) for f in dados)
    if not total:
        return empty_chart(size, size, "Sem dados")

    raio = (size - thickness) / 2 - 4
    cx = cy = size / 2
    circunferencia = 2 * math.pi * raio
    offset = 0.0
    partes = [
        f'<svg class="chart donut" viewBox="0 0 {size} {size}" role="img" '
        f'aria-label="Participação por categoria" xmlns="http://www.w3.org/2000/svg">',
        f'<circle cx="{cx}" cy="{cy}" r="{raio:.1f}" fill="none" class="track" stroke-width="{thickness}"/>',
    ]
    for idx, fatia in enumerate(dados):
        valor = int(fatia.get("total") or 0)
        pedaco = valor / total * circunferencia
        cor = fatia.get("color") or PALETTE[idx % len(PALETTE)]
        rotacao = offset / circunferencia * 360 - 90
        partes.append(
            f'<circle cx="{cx}" cy="{cy}" r="{raio:.1f}" fill="none" stroke="{esc(cor)}" '
            f'stroke-width="{thickness}" stroke-dasharray="{pedaco:.2f} {circunferencia - pedaco:.2f}" '
            f'transform="rotate({rotacao:.2f} {cx} {cy})">'
            f'<title>{esc(fatia.get("name"))}: R$ {esc(format_centavos(valor))} '
            f'({valor / total * 100:.1f}%)</title></circle>'
        )
        offset += pedaco
    partes.append(
        f'<text x="{cx}" y="{cy - 4}" class="donut-label" text-anchor="middle">{esc(center_label)}</text>'
        f'<text x="{cx}" y="{cy + 18}" class="donut-value" text-anchor="middle">{esc(center_value)}</text>'
        f"</svg>"
    )
    return "".join(partes)


def line_chart(
    pontos: Sequence[dict[str, Any]],
    width: int = 760,
    height: int = 260,
    title: str = "Saldo acumulado",
    value_key: str = "acumulado",
) -> str:
    """Linha de evolução (usada para o saldo acumulado)."""
    valores = [int(p.get(value_key) or 0) for p in pontos]
    if not valores:
        return empty_chart(width, height, "Sem dados")
    pad_l, pad_r, pad_t, pad_b = 64, 16, 34, 40
    plot_w, plot_h = width - pad_l - pad_r, height - pad_t - pad_b
    maior, menor = max(valores), min(valores)
    teto = _nice_max(max(maior, 1))
    piso = -_nice_max(abs(menor)) if menor < 0 else 0
    amplitude = teto - piso or 1

    def y(valor: int) -> float:
        return pad_t + plot_h - (valor - piso) / amplitude * plot_h

    coords = []
    for idx, ponto in enumerate(pontos):
        x = pad_l + (plot_w * idx / max(1, len(pontos) - 1))
        coords.append((x, y(int(ponto.get(value_key) or 0)), ponto))

    linha = " ".join(f"{x:.1f},{yy:.1f}" for x, yy, _ in coords)
    area = f"{pad_l},{y(0):.1f} " + linha + f" {pad_l + plot_w},{y(0):.1f}"

    partes = [
        f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="{esc(title)}" '
        f'xmlns="http://www.w3.org/2000/svg">',
        f'<text x="{pad_l}" y="20" class="chart-title">{esc(title)}</text>',
    ]
    for i in range(5):
        valor = piso + amplitude * i / 4
        yy = y(int(valor))
        partes.append(
            f'<line x1="{pad_l}" y1="{yy:.1f}" x2="{width - pad_r}" y2="{yy:.1f}" class="grid"/>'
            f'<text x="{pad_l - 8}" y="{yy + 4:.1f}" class="axis" text-anchor="end">{esc(compact_brl(int(valor)))}</text>'
        )
    if piso < 0:
        partes.append(f'<line x1="{pad_l}" y1="{y(0):.1f}" x2="{width - pad_r}" y2="{y(0):.1f}" class="axis-line"/>')
    partes.append(f'<polygon points="{area}" class="area"/>')
    partes.append(f'<polyline points="{linha}" class="line"/>')
    for x, yy, ponto in coords:
        cor = COR_ENTRADA if int(ponto.get(value_key) or 0) >= 0 else COR_SAIDA
        partes.append(
            f'<circle cx="{x:.1f}" cy="{yy:.1f}" r="4" fill="{cor}">'
            f'<title>{esc(ponto.get("label"))}: {esc(compact_brl(int(ponto.get(value_key) or 0)))}</title></circle>'
            f'<text x="{x:.1f}" y="{height - pad_b + 20}" class="axis" text-anchor="middle">{esc(ponto.get("label"))}</text>'
        )
    partes.append("</svg>")
    return "".join(partes)


def empty_chart(width: int, height: int, message: str = "Sem dados") -> str:
    return (
        f'<svg class="chart empty" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">'
        f'<text x="{width / 2}" y="{height / 2}" class="axis" text-anchor="middle">{esc(message)}</text></svg>'
    )
