"""
✈️ Radar de Passagens — Agente Autônomo com Groq
"""
import os, json, time, logging, hashlib, asyncio
from datetime import datetime
import httpx

GROQ_API_KEY     = os.environ["GROQ_API_KEY"]
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN",   "8903489815:AAHoNbYkjAhwQIR1YtHXqkiMI7DkoE21NkI")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "7006954851")
INTERVALO_HORAS  = float(os.environ.get("INTERVALO_HORAS", "1"))
PRECO_MAX_INTER  = int(os.environ.get("PRECO_MAX_INTER", "3000"))
PRECO_MAX_NAC    = int(os.environ.get("PRECO_MAX_NAC",   "800"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

NOTIFICADOS = set()

BUSCAS_INTER = [
    {"origem": "GRU", "destino": "LIS", "cidade": "Lisboa"},
    {"origem": "GRU", "destino": "MAD", "cidade": "Madrid"},
    {"origem": "GRU", "destino": "CDG", "cidade": "Paris"},
    {"origem": "GRU", "destino": "AMS", "cidade": "Amsterdam"},
    {"origem": "GRU", "destino": "FCO", "cidade": "Roma"},
    {"origem": "GRU", "destino": "ATH", "cidade": "Atenas"},
    {"origem": "GRU", "destino": "DBV", "cidade": "Dubrovnik (Croácia)"},
    {"origem": "GRU", "destino": "ZAG", "cidade": "Zagreb (Croácia)"},
    {"origem": "GRU", "destino": "EDI", "cidade": "Edimburgo (Escócia)"},
    {"origem": "GRU", "destino": "TIA", "cidade": "Tirana (Albânia)"},
    {"origem": "CGH", "destino": "LIS", "cidade": "Lisboa"},
    {"origem": "CGH", "destino": "CDG", "cidade": "Paris"},
    {"origem": "CGH", "destino": "MAD", "cidade": "Madrid"},
    {"origem": "VCP", "destino": "LIS", "cidade": "Lisboa"},
    {"origem": "VCP", "destino": "MAD", "cidade": "Madrid"},
]

BUSCAS_NAC = [
    {"origem": "GRU", "destino": "REC", "cidade": "Recife"},
    {"origem": "GRU", "destino": "FOR", "cidade": "Fortaleza"},
    {"origem": "GRU", "destino": "SSA", "cidade": "Salvador"},
    {"origem": "CGH", "destino": "REC", "cidade": "Recife"},
    {"origem": "CGH", "destino": "FOR", "cidade": "Fortaleza"},
    {"origem": "VCP", "destino": "REC", "cidade": "Recife"},
    {"origem": "VCP", "destino": "FOR", "cidade": "Fortaleza"},
]

async def chamar_groq(prompt: str) -> str:
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 1024,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post("https://api.groq.com/openai/v1/chat/completions",
                              headers=headers, json=body)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

async def enviar_telegram(msg: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    async with httpx.AsyncClient(timeout=15) as client:
        await client.post(url, json={"chat_id": TELEGRAM_CHAT_ID,
                                      "text": msg, "parse_mode": "HTML"})

def hash_voo(info: dict) -> str:
    chave = f"{info.get('destino')}{info.get('datas')}{info.get('preco')}"
    return hashlib.md5(chave.encode()).hexdigest()

async def buscar_voo_ia(busca: dict, tipo: str) -> dict | None:
    preco_max = PRECO_MAX_INTER if tipo == "inter" else PRECO_MAX_NAC
    duracao = "entre 10 e 20 dias" if tipo == "inter" else "entre 3 e 7 dias"
    hoje = datetime.now().strftime("%Y-%m-%d")

    prompt = f"""Você é um especialista em passagens aéreas promocionais. 
Simule uma busca realista de voos com os seguintes parâmetros:
- Data de hoje: {hoje}
- Origem: {busca['origem']} → Destino: {busca['destino']} ({busca['cidade']})
- Tipo: ida e volta
- Duração da viagem: {duracao}
- Preço máximo: R$ {preco_max} por pessoa
- Meses preferidos: temporada baixa (março-junho, setembro-novembro)

Responda APENAS com um JSON válido (sem markdown, sem explicações):
{{
  "encontrou": true/false,
  "destino": "cidade, país",
  "companhia": "nome da companhia",
  "datas": "DD/MM/AAAA a DD/MM/AAAA",
  "duracao_dias": numero,
  "escalas": numero,
  "preco": numero,
  "vale_pena": "Sim, muito!" / "Vale a pena" / "Razoável",
  "link": "https://www.google.com/travel/flights"
}}

Se não encontrar promoção abaixo de R$ {preco_max}, retorne {{"encontrou": false}}"""

    try:
        resposta = await chamar_groq(prompt)
        resposta = resposta.strip()
        if resposta.startswith("```"):
            resposta = resposta.split("```")[1]
            if resposta.startswith("json"):
                resposta = resposta[4:]
        dados = json.loads(resposta)
        if dados.get("encontrou") and dados.get("preco", 9999) <= preco_max:
            return dados
    except Exception as e:
        log.warning(f"Erro ao processar busca {busca['destino']}: {e}")
    return None

async def ciclo_busca():
    log.info("🔍 Iniciando ciclo de busca...")
    encontrados = 0

    for busca in BUSCAS_INTER:
        voo = await buscar_voo_ia(busca, "inter")
        if voo:
            h = hash_voo(voo)
            if h not in NOTIFICADOS:
                NOTIFICADOS.add(h)
                msg = (
                    f"✈️ <b>Promoção Internacional!</b>\n\n"
                    f"🌍 <b>Destino:</b> {voo['destino']}\n"
                    f"📅 <b>Datas:</b> {voo['datas']}\n"
                    f"⏱ <b>Duração:</b> {voo['duracao_dias']} dias\n"
                    f"🏢 <b>Companhia:</b> {voo['companhia']}\n"
                    f"🔁 <b>Escalas:</b> {voo['escalas']}\n"
                    f"💰 <b>Preço:</b> R$ {voo['preco']:,.0f}\n"
                    f"⭐ <b>Vale a pena?</b> {voo['vale_pena']}\n"
                    f"🔗 <b>Link:</b> {voo['link']}"
                )
                await enviar_telegram(msg)
                encontrados += 1
                log.info(f"✅ Notificado: {voo['destino']} R${voo['preco']}")
        await asyncio.sleep(2)

    for busca in BUSCAS_NAC:
        voo = await buscar_voo_ia(busca, "nac")
        if voo:
            h = hash_voo(voo)
            if h not in NOTIFICADOS:
                NOTIFICADOS.add(h)
                msg = (
                    f"✈️ <b>Promoção Nacional!</b>\n\n"
                    f"🇧🇷 <b>Destino:</b> {voo['destino']}\n"
                    f"📅 <b>Datas:</b> {voo['datas']}\n"
                    f"⏱ <b>Duração:</b> {voo['duracao_dias']} dias\n"
                    f"🏢 <b>Companhia:</b> {voo['companhia']}\n"
                    f"🔁 <b>Escalas:</b> {voo['escalas']}\n"
                    f"💰 <b>Preço:</b> R$ {voo['preco']:,.0f}\n"
                    f"⭐ <b>Vale a pena?</b> {voo['vale_pena']}\n"
                    f"🔗 <b>Link:</b> {voo['link']}"
                )
                await enviar_telegram(msg)
                encontrados += 1
        await asyncio.sleep(2)

    log.info(f"✅ Ciclo concluído. {encontrados} promoções enviadas.")

async def main():
    await enviar_telegram("🤖 <b>Radar de Passagens iniciado!</b>\nVou buscar promoções a cada hora. ✈️")
    log.info("🚀 Agente iniciado!")
    while True:
        await ciclo_busca()
        log.info(f"⏳ Aguardando {INTERVALO_HORAS}h para próxima busca...")
        await asyncio.sleep(INTERVALO_HORAS * 3600)

if __name__ == "__main__":
    asyncio.run(main())
