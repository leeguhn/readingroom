import requests, json

with open('UIST_2025_program.json', encoding='utf-8') as f:
    data = json.load(f)
papers = [p for p in data['contents'] if p.get('title')][:3]

SYSTEM = (
    '/no_think\n'
    'You are screening academic papers. Answer YES, MAYBE, or NO for whether each paper '
    'is related to AI image generation interfaces (e.g. text-to-image tools, diffusion model UIs, '
    'image synthesis interfaces, generative image tools).\n\n'
    'For EACH paper, output exactly one line:\n'
    '  <number>|<verdict>|<reason>\n'
    'reason = 5-10 words. Output ONLY these lines.'
)

lines = ['Papers to screen:']
for i, p in enumerate(papers, 1):
    snippet = p.get('abstract', '')[:300]
    lines.append(f"\n{i}. {p['title']}\n   {snippet}")

r = requests.post('http://127.0.0.1:1234/v1/chat/completions', json={
    'model': 'qwen/qwen3.5-9b',
    'messages': [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': '\n'.join(lines)}],
    'temperature': 0.1, 'max_tokens': 512, 'stream': False
}, timeout=60)
raw = r.json()['choices'][0]['message']['content']
print('=== RAW OUTPUT ===')
print(repr(raw))
print()
print('=== PRINTED ===')
print(raw)
