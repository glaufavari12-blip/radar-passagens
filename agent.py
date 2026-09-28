"""
✈️ Radar de Passagens — Agente Autônomo
Roda a cada hora, busca promoções via Claude AI e notifica via Telegram.
"""

import os
import json
import time
import logging
import hashlib
import asyncio
from datetime import datetime
import httpx

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
TELEGRAM_TOKEN    = os.environ.get("TELEGRAM_TOKEN",   "8903489815:AAH0NbYkjAhwQIR1YtHXqkiMI7DkoE21NkI")
TELEGRAM_CHAT_ID  = os.environ.get("TELEGRAM_CHAT_ID", "7006954851")

INTERVALO_HORAS  = float(os.environ.get("INTERVALO_HORAS", "1"))
PRECO_MAX_INTER  = int(os.environ.get("PRECO_MAX_INTER",  "4000"))
PRECO_MAX_NAC    = int(os.environ.get("PRECO_MAX_NAC",    "800"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger("radar")

ofertas_notificadas: set[str] = set()

def hash_oferta(voo: dict) -> str:
    chave = f"{voo.get('origem_iata')}-{voo.get('destino_iata')}-{voo.get('data_ida')}-{voo.get('data_volta')}-{voo.get('preco_total')}"
    return hashlib.md5(chave.encode()).hexdigest()

PROMPT_INTER = f"""Você é um agente especialista em passagens aéreas promocionais.
Simule uma busca realista de voos internacionais São Paulo → Europa para a data atual.
REGRAS:
- Origem: GRU (Guarulhos) ou CGH (Congonhas)
- Destino: Europa, ida e volta para GRU/CGH
- Duração: entre 15 e 20 dias
- Limite: R$ {PRECO_MAX_INTER} por pessoa ida+volta
DESTINOS PRIORITÁRIOS: Portugal (LIS/OPO), França (CDG), Holanda (AMS), Escócia (EDI/GLA), Espanha (MAD/BCN)
Companhias preferidas: TAP, Air France, KLM, Iberia, LATAM, British Airways, Lufthansa.
Gere entre 4 e 6 opções realistas.
Responda SOMENTE JSON válido, sem markdown:
{{"voos": [{{"tipo": "internacional","destino_cidade": "string","destino_pais": "string","pais_emoji": "string","destino_iata": "string","origem_iata": "string","companhia": "string","data_ida": "string","data_volta": "string","duracao_dias": 0,"escalas_ida": 0,"escalas_volta": 0,"cidades_escala": null,"preco_total": 0,"dentro_limite": true,"vale_muito": true,"motivo": "string","link_busca": "string"}}]}}"""

PROMPT_NACIONAL = f"""Você é um agente especialista em passagens aéreas nacionais promocionais.
Simule uma busca realista de voos nacionais São Paulo → Nordeste para a data atual.
REGRAS:
- Origem: GRU ou CGH
- Destino: Nordeste, ida e volta, duração 7 a 15 dias
- Limite: R$ {PRECO_MAX_NAC} por pessoa ida+volta
- Destinos: FOR, REC, SSA, NAT, MCZ — Companhias: LATAM, Gol, Azul
Gere entre 3 e 5 opções realistas.
Responda SOMENTE JSON válido, sem markdown:
{{"voos": [{{"tipo": "nacional","destino_cidade": "string","destino_estado": "string","pais_emoji": "🇧🇷","destino_iata": "string","origem_iata": "string","companhia": "string","data_ida": "string","data_volta": "string","duracao_dias": 0,"escalas_ida": 0,"escalas_volta": 0,"preco_total": 0,"dentro_limite": true,"vale_muito": true,"motivo": "string","link_busca": "string"}}]}}"""

async def buscar_voos(client: httpx.AsyncClient, system_prompt: str, tipo: str) -> list[dict]:
    log.info(f"🔍 Buscando voos {tipo}...")
    try:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": "claude-sonnet-4-20250514", "max_tokens": 1000, "system": system_prompt, "messages": [{"role": "user", "content": f"Busque promoções agora. Data: {datetime.now().strftime('%d/%m/%Y %H:%M')}"}]},
            timeout=60.0
        )
        resp.raise_for_status()
        data = resp.json()
        text = "".join(b.get("text", "") for b in data.get("content", []))
        parsed = json.loads(text.replace("```json", "").replace("```", "").strip())
        voos = parsed.get("voos", [])
        log.info(f"✅ {len(voos)} voos {tipo} encontrados")
        return voos
    except Exception as e:
        log.error(f"❌ Erro buscando {tipo}: {e}")
        return []

async def enviar_telegram(client: httpx.AsyncClient, texto: str):
    try:
        resp = await client.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": texto, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=15.0)
        resp.raise_for_status()
        log.info("📨 Mensagem enviada ao Telegram")
    except Exception as e:
        log.error(f"❌ Erro Telegram: {e}")

def formatar_mensagem(voo: dict, limite: int) -> str:
    escalas = (voo.get("escalas_ida") or 0) + (voo.get("escalas_volta") or 0)
    escala_txt = "Direto ✈️" if escalas == 0 else f"{escalas} escala(s)"
    if voo.get("cidades_escala"):
        escala_txt += f" via {voo['cidades_escala']}"
    preco = voo.get("preco_total", 0)
    ok = preco <= limite
    top = voo.get("vale_muito", False)
    destaque = "\n⚡ <b>TOP DEAL — Não perca!</b>" if top else ""
    return (
        f"✈️ <b>PROMOÇÃO ENCONTRADA!{destaque}</b>\n\n"
        f"{voo.get('pais_emoji','🌍')} <b>Destino:</b> {voo.get('destino_cidade','?')}, {voo.get('destino_pais') or voo.get('destino_estado','')}\n"
        f"🛫 <b>Rota:</b> {voo.get('origem_iata','?')} → {voo.get('destino_iata','?')}\n"
        f"📅 <b>Ida:</b> {voo.get('data_ida','?')}\n"
        f"📅 <b>Volta:</b> {voo.get('data_volta','?')}\n"
        f"🗓 <b>Duração:</b> {voo.get('duracao_dias','?')} dias\n"
        f"🏢 <b>Companhia:</b> {voo.get('companhia','?')}\n"
        f"🔄 <b>Escalas:</b> {escala_txt}\n"
        f"💰 <b>Preço:</b> R$ {preco:,.0f} por pessoa\n"
        f"📊 <b>Status:</b> {'✅ DENTRO DO LIMITE' if ok else '⚠️ ACIMA DO LIMITE'}\n"
        f"💡 <b>Vale a pena?</b> {voo.get('motivo','')}\n\n"
        f"🔍 <a href=\"{voo.get('link_busca','')}\">Buscar no Google Flights</a>"
    )

async def ciclo_busca():
    async with httpx.AsyncClient() as client:
        await enviar_telegram(client,
            "🤖 <b>Olá, Glau! Radar de Passagens ATIVO! ✈️</b>\n\n"
            f"🔁 Buscando a cada <b>{int(INTERVALO_HORAS)}h</b>\n"
            f"🌍 Europa (GRU/CGH): até R$ {PRECO_MAX_INTER:,}\n"
            f"🇧🇷 Nordeste (GRU/CGH): até R$ {PRECO_MAX_NAC:,}\n\n"
            "Você será avisada quando encontrar promoções! 🎯"
        )
        while True:
            log.info(f"⏰ Ciclo iniciado — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
            inter_voos, nac_voos = await asyncio.gather(
                buscar_voos(client, PROMPT_INTER, "internacional"),
                buscar_voos(client, PROMPT_NACIONAL, "nacional")
            )
            novas = 0
            for voos, limite in [(inter_voos, PRECO_MAX_INTER), (nac_voos, PRECO_MAX_NAC)]:
                for voo in voos:
                    if not voo.get("dentro_limite") and not voo.get("vale_muito"):
                        continue
                    hk = hash_oferta(voo)
                    if hk in ofertas_notificadas:
                        continue
                    await enviar_telegram(client, formatar_mensagem(voo, limite))
                    ofertas_notificadas.add(hk)
                    novas += 1
                    await asyncio.sleep(1.5)
            log.info(f"🎉 {novas} oferta(s) notificada(s)!" if novas else "😴 Nenhuma oferta nova.")
            if len(ofertas_notificadas) > 500:
                ofertas_notificadas.clear()
            await asyncio.sleep(INTERVALO_HORAS * 3600)

if __name__ == "__main__":
    log.info("✈️  Radar de Passagens iniciando...")
    asyncio.run(ciclo_busca())
