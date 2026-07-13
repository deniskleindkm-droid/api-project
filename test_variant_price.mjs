import fs from 'fs';
import http from 'http';

function fetchJson(path) {
  return new Promise((resolve, reject) => {
    http.get({ host: '127.0.0.1', port: 8000, path }, res => {
      let data = '';
      res.on('data', c => data += c);
      res.on('end', () => resolve(JSON.parse(data)));
    }).on('error', reject);
  });
}

// Load the EXACT shipped function text, not a re-typed copy.
const html = fs.readFileSync('docs/index.html', 'utf8');
const start = html.indexOf('function updateVariantPrice()');
const end = html.indexOf('\nfunction selectChip');
const fnSrc = html.slice(start, end);

// Minimal stub environment matching what updateVariantPrice() touches.
let ppSelectedSize = null, ppSelectedColor = null, ppSelectedColorRaw = null;
let ppSelectedStone = null, ppSelectedWidth = null;
let ppSelectedOptionId = null;
let ppVariantPrices = [];
let priceElText = '';
const document = {
  getElementById: (id) => {
    if (id === 'pp-price') {
      return {
        get textContent() { return priceElText; },
        set textContent(v) { priceElText = v; },
        style: {},
      };
    }
    throw new Error('unexpected getElementById: ' + id);
  }
};
// updateVariantPrice uses setTimeout for a fade animation; run it synchronously for the test.
const setTimeout = (fn) => fn();

const updateVariantPrice = new Function(
  'document', 'setTimeout',
  `${fnSrc}
   return updateVariantPrice;`
)(document, setTimeout);

// Need closures over the let-bound state — re-implement via a factory that shares scope.
function makeRunner() {
  const ctx = { ppSelectedSize:null, ppSelectedColor:null, ppSelectedColorRaw:null,
                ppSelectedStone:null, ppSelectedWidth:null, ppSelectedOptionId:null,
                ppVariantPrices:[] };
  const fn = new Function('document','setTimeout', `
    ${fnSrc}
    return function(state){
      ppSelectedSize=state.ppSelectedSize; ppSelectedColor=state.ppSelectedColor;
      ppSelectedColorRaw=state.ppSelectedColorRaw; ppSelectedStone=state.ppSelectedStone;
      ppSelectedWidth=state.ppSelectedWidth; ppVariantPrices=state.ppVariantPrices;
      updateVariantPrice();
      return {ppSelectedOptionId, price: document.getElementById('pp-price').textContent};
    };
  `)(document, setTimeout);
  return fn;
}

const run = makeRunner();

(async () => {
  console.log('=== Product 1011: Six Pointed Star Moissanite Pendant Necklace ===');
  const vp1011 = await fetchJson('/products/1011/variant-prices');
  console.log('Real API data:', JSON.stringify(vp1011, null, 2));

  const tests1011 = [
    { label: 'White Gold + Pendant Only', ppSelectedColorRaw: 'White Gold · D Color Moissanite · Pendant Only', expectPrice: '$88.90', expectOptionId: '58689' },
    { label: 'White Gold + With Necklace', ppSelectedColorRaw: 'White Gold · D Color Moissanite · With Necklace', expectPrice: '$111.90', expectOptionId: '58690' },
    { label: 'Yellow Gold + Pendant Only', ppSelectedColorRaw: 'Yellow Gold · D Color Moissanite · Pendant Only', expectPrice: '$88.90', expectOptionId: '58691' },
    { label: 'Yellow Gold + With Necklace', ppSelectedColorRaw: 'Yellow Gold · D Color Moissanite · With Necklace', expectPrice: '$111.90', expectOptionId: '58692' },
  ];
  for (const t of tests1011) {
    priceElText = '';
    const result = run({ ppSelectedSize: null, ppSelectedColor: t.ppSelectedColorRaw, ppSelectedColorRaw: t.ppSelectedColorRaw, ppSelectedStone: null, ppSelectedWidth: null, ppVariantPrices: vp1011 });
    const ok = result.price === t.expectPrice && result.ppSelectedOptionId === t.expectOptionId;
    console.log(`  [${ok ? 'PASS' : 'FAIL'}] ${t.label} -> price=${result.price} option_id=${result.ppSelectedOptionId} (expected ${t.expectPrice} / ${t.expectOptionId})`);
  }

  console.log();
  console.log('=== Product 632: Birthstone Stud Earrings (two-tier selector: Color chip + Stone chip) ===');
  const vp632 = await fetchJson('/products/632/variant-prices');
  console.log(`Real API data: ${vp632.length} options, sample:`, JSON.stringify(vp632.slice(0,3), null, 2));

  // Simulates the actual UI flow: customer picks a Color chip (metal) AND a separate
  // Stone chip. THIS is the exact bug scenario — ppSelectedStone must now be honored.
  const tests632 = [
    { label: 'Silver + Black (stone)', ppSelectedColorRaw: 'Silver', ppSelectedStone: 'Black' },
    { label: 'Silver + Sapphire Blue (stone)', ppSelectedColorRaw: 'Silver', ppSelectedStone: 'Sapphire Blue' },
    { label: 'Yellow Gold + Emerald Green (stone)', ppSelectedColorRaw: 'Yellow Gold', ppSelectedStone: 'Emerald Green' },
  ];
  for (const t of tests632) {
    priceElText = '';
    const result = run({ ppSelectedSize: null, ppSelectedColor: t.ppSelectedColorRaw, ppSelectedColorRaw: t.ppSelectedColorRaw, ppSelectedStone: t.ppSelectedStone, ppSelectedWidth: null, ppVariantPrices: vp632 });
    const expected = vp632.find(v => v.color.toLowerCase() === `${t.ppSelectedColorRaw} · ${t.ppSelectedStone}`.toLowerCase());
    const expectPrice = expected ? `$${expected.final_price.toFixed(2)}` : null;
    const expectOptionId = expected ? String(expected.option_id) : null;
    const ok = result.price === expectPrice && result.ppSelectedOptionId === expectOptionId;
    console.log(`  [${ok ? 'PASS' : 'FAIL'}] ${t.label} -> price=${result.price} option_id=${result.ppSelectedOptionId} (expected ${expectPrice} / ${expectOptionId})`);
  }

  // Regression check: with the OLD buggy logic (ignoring ppSelectedStone), every one
  // of the three tests632 selections above would have resolved to the SAME first
  // matching color-only entry regardless of stone — verify that's no longer true.
  console.log();
  const results = tests632.map(t => {
    priceElText = '';
    return run({ ppSelectedSize: null, ppSelectedColor: t.ppSelectedColorRaw, ppSelectedColorRaw: t.ppSelectedColorRaw, ppSelectedStone: t.ppSelectedStone, ppSelectedWidth: null, ppVariantPrices: vp632 }).ppSelectedOptionId;
  });
  const allDistinctDespiteStoneChange = new Set(results).size === results.length;
  console.log(`Regression check — distinct option_ids across different stone selections: ${JSON.stringify(results)} -> ${allDistinctDespiteStoneChange ? 'PASS (bug fixed)' : 'FAIL (still collapsing)'}`);

  console.log();
  console.log('=== Product 634: Cubic Zirconia Huggie Hoops Earring (plain size + color, no stone/width — regression check) ===');
  const vp634 = await fetchJson('/products/634/variant-prices');
  const tests634 = [
    { label: '6mm + Yellow Gold', size: '6mm', color: 'Yellow Gold', expectOptionId: '57012', expectPrice: '$51.90' },
    { label: '9mm + Yellow Gold', size: '9mm', color: 'Yellow Gold', expectOptionId: '57015', expectPrice: '$55.00' },
    { label: '8mm + Silver',      size: '8mm', color: 'Silver',      expectOptionId: '57019', expectPrice: '$53.90' },
    { label: '10mm + Silver',     size: '10mm', color: 'Silver',     expectOptionId: '57021', expectPrice: '$55.90' },
  ];
  for (const t of tests634) {
    priceElText = '';
    const result = run({ ppSelectedSize: t.size, ppSelectedColor: t.color, ppSelectedColorRaw: t.color, ppSelectedStone: null, ppSelectedWidth: null, ppVariantPrices: vp634 });
    const ok = result.price === t.expectPrice && result.ppSelectedOptionId === t.expectOptionId;
    console.log(`  [${ok ? 'PASS' : 'FAIL'}] ${t.label} -> price=${result.price} option_id=${result.ppSelectedOptionId} (expected ${t.expectPrice} / ${t.expectOptionId})`);
  }
})();
