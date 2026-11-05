from jinja2 import Environment, FileSystemLoader
import json

env = Environment(loader=FileSystemLoader('.'))
with open('sample_page1.json', 'r') as f:
    base_data = json.load(f)

# Add dummy data for pages 2, 3, 4
base_data['ledger_rows'] = [
    {'ln': '01', 'date': '03 Oct', 'receipt': 'MPX-6718', 'category': 'Transport', 'paid_to': 'Umoja Shuttle Sacco', 'amount': '4,800', 'evidence': 'Verified'},
    {'ln': '02', 'date': '05 Oct', 'receipt': 'RCT-1042', 'category': 'Pitch fees', 'paid_to': 'Nairobi Sports Ground', 'amount': '3,500', 'evidence': 'Receipt attached'},
    # ... add the rest ...
]

base_data['players'] = [{'amount': '750'} for _ in range(18)]

base_data['receipts'] = [
    {'ln': '01', 'initials': 'US', 'supplier': 'Umoja Shuttle Sacco', 'date': '03 Oct 2026', 'ref': 'MPX-6718', 'purpose': 'Transport', 'amount': 'KES 4,800', 'status': 'PAID'},
    {'ln': '02', 'initials': 'NS', 'supplier': 'Nairobi Sports Ground', 'date': '05 Oct 2026', 'ref': 'RCT-1042', 'purpose': 'Pitch fees', 'amount': 'KES 3,500', 'status': 'PAID'},
    # ... add the rest ...
]

pages = ['page1_summary.html.j2', 'page2_ledger.html.j2', 'page3_squad.html.j2', 'page4_receipts.html.j2']
html_out = ""
for page in pages:
    template = env.get_template(page)
    html_out += template.render(**base_data)

with open('preview_full.html', 'w', encoding='utf-8') as f:
    f.write(html_out)
print('Done! Open preview_full.html')