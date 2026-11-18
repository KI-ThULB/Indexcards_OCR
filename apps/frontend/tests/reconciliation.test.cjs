const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const ts = require('typescript');
const { QueryClient } = require('@tanstack/query-core');

const frontend = path.resolve(__dirname, '..');

function loadSource(filename, dependencies, globals = {}) {
  const source = readFileSync(path.join(frontend, filename), 'utf8');
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  });
  const exports = {};
  vm.runInNewContext(outputText, { exports, require: id => dependencies[id], ...globals });
  return exports;
}

const field = 'KÜNSTLER';
const uri = 'https://d-nb.info/gnd/118540238';
const manual = {
  authority: 'gnd-persons', uri, label: 'Künstler', picked_by: 'manual',
  picked_at: '2026-01-01T00:00:00Z',
};
const automatic = { ...manual, picked_by: 'auto' };

function row(filename, value, reconciliation) {
  return {
    filename, status: 'success', duration: 0,
    data: { [field]: value }, editedData: {},
    ...(reconciliation === undefined ? {} : {
      validation: { [field]: { status: 'valid', reconciliation } },
    }),
  };
}

function exportHarness() {
  let confirm;
  const downloads = [];
  let content;
  const { useResultsExport } = loadSource('src/features/results/useResultsExport.ts', {
    sonner: { toast: { warning: (_message, options) => { confirm = options.action.onClick; } } },
    '../../api/batchesApi': { reportExportEvent() {} },
    './groupValue': loadSource('src/features/results/groupValue.ts', {}),
  }, {
    URL: class extends URL {
      static createObjectURL() { return 'blob:test'; }
      static revokeObjectURL() {}
    },
    Blob: class {
      constructor(chunks) { content = chunks.join(''); }
    },
    document: {
      createElement() { return { click() { downloads.push(content); } }; },
    },
  });
  return { useResultsExport, downloads, confirm: () => confirm() };
}

function exportsFor(rows, bindings, fields = [field], groups = null) {
  const { useResultsExport, downloads } = exportHarness();
  const actions = useResultsExport('batch', () => [rows, fields, 'batch', groups, bindings]);
  actions.downloadCSV();
  actions.downloadJSON();
  actions.downloadLIDO();
  return { csv: downloads[0], json: JSON.parse(downloads[1]), lido: downloads[2] };
}

test('CSV appends authority URI and JSON preserves both confirmation modes and OCR', () => {
  const rows = [
    row('manual.jpg', 'Name, "A"', manual),
    row('auto.jpg', 'Auto', automatic),
    row('legacy.jpg', 'Legacy'),
    row('rejected.jpg', 'Rejected', null),
    row('invalid.jpg', 'Invalid URI', { ...manual, uri: 'javascript:example' }),
    { ...row('cleared.jpg', 'Former OCR', manual), editedData: { [field]: '' } },
    { ...row('entries.jpg', 'Old', manual), data: {
      _entries: JSON.stringify([{ [field]: 'One' }, { [field]: 'Two' }]),
    } },
  ];
  const { csv, json, lido } = exportsFor(rows, { [field]: { type: 'gnd-persons' } });
  const [header, user, auto, ...unlinked] = csv.split('\r\n');
  assert.ok(header.endsWith('"KÜNSTLER_ocr","KÜNSTLER_edited","KÜNSTLER_confidence","KÜNSTLER_authority_uri"'));
  assert.ok(user.endsWith(`"Name, ""A""","","","${uri}"`));
  assert.ok(auto.endsWith(`,"${uri}"`));
  assert.equal(unlinked.length, 6);
  assert.ok(unlinked.every(line => line.endsWith(',""') && !line.includes(uri)));
  assert.deepEqual(json[0].fields[field], { ocr: 'Name, "A"', reconciliation: manual });
  assert.deepEqual(json[1].fields[field], { ocr: 'Auto', reconciliation: automatic });
  assert.ok(json.slice(2).every(entry => !('reconciliation' in entry.fields[field])));
  assert.deepEqual(json.slice(-2).map(entry => entry.fields[field].ocr), ['One', 'Two']);
  assert.doesNotMatch(lido, /<lido:objectDescriptionSet[^>]*>\s*<lido:conceptID/);
});

test('legacy shape is preserved and stored outcomes or bindings alone reserve URI columns', () => {
  const legacy = row('legacy.jpg', 'Legacy');
  assert.doesNotMatch(exportsFor([legacy]).csv, /_authority_uri/);
  assert.deepEqual(exportsFor([legacy]).json[0].fields[field], { ocr: 'Legacy' });
  assert.match(exportsFor([legacy], { [field]: { type: 'gnd-persons' } }).csv, /_authority_uri/);
  assert.match(exportsFor([row('matched.jpg', 'Matched', manual)]).csv, /_authority_uri/);
});

test('repeatable columns keep their position and reject a group-level match', () => {
  const card = row('card.jpg', 'Name', manual);
  card.data.Credits = JSON.stringify([{ Role: 'One' }, { Role: 'Two' }]);
  card.validation.Credits = { status: 'valid', reconciliation: manual };
  const groups = { Credits: { fields: [{ name: 'Role' }], max_items: 2 } };
  const { csv, json } = exportsFor([card], null, ['Credits', field], groups);
  const [header, line] = csv.split('\r\n');
  assert.match(header, /Credits.*Credits.*KÜNSTLER_ocr.*KÜNSTLER_authority_uri/);
  assert.doesNotMatch(header, /Credits_authority_uri/);
  assert.equal(header.split(',').length, line.split(',').length);
  assert.doesNotMatch(JSON.stringify(json[0].fields.Credits), /reconciliation/);
});

test('confirmed PATCH replaces stale query data and a failed PATCH leaves it intact', async () => {
  const client = new QueryClient();
  const key = ['results', 'batch'];
  const original = { filename: 'card.jpg', data: { [field]: 'Name' } };
  const confirmed = { ...original, validation: { [field]: { reconciliation: manual } } };
  client.setQueryData(key, { results: [original], audit: [] });
  let resolveRead;
  const staleRead = client.fetchQuery({
    queryKey: key,
    queryFn: () => new Promise(resolve => { resolveRead = resolve; }),
  }).catch(() => {});
  let fail = false;
  const { useSyncedResultPatch, resultWriteStatus } = loadSource('src/api/batchesApi.ts', {
    axios: { default: { patch: async () => {
      if (fail) throw new Error('PATCH failed');
      return { data: { result: confirmed } };
    } } },
    react: { useCallback: fn => fn },
    '@tanstack/react-query': {
      useQueryClient: () => client,
      useMutation: options => ({ mutateAsync: args => client.getMutationCache().build(client, options).execute(args) }),
    },
    sonner: {},
  });
  const patch = useSyncedResultPatch();
  const request = patch('batch', 'card.jpg', { field, reconciliation: manual });
  assert.equal(resultWriteStatus(client, 'batch'), 'pending');
  assert.equal(resultWriteStatus(client, 'other'), 'ready');
  assert.equal(await request, confirmed);
  resolveRead({ results: [original], audit: [] });
  await staleRead;
  assert.equal(client.getQueryData(key).results[0], confirmed);
  fail = true;
  await assert.rejects(patch('batch', 'card.jpg', { field, clear_reconciliation: true }), /PATCH failed/);
  assert.equal(client.getQueryData(key).results[0], confirmed);
  assert.equal(resultWriteStatus(client, 'batch'), 'failed');
  fail = false;
  await patch('batch', 'card.jpg', { field, validation_status: 'verified' });
  assert.equal(resultWriteStatus(client, 'batch'), 'failed');
  // A lost response is resolved by inspecting the stored row. No second PATCH.
  fail = true;
  await patch('batch', 'card.jpg', { field, clear_reconciliation: true }, async () => confirmed);
  assert.equal(resultWriteStatus(client, 'batch'), 'ready');
});

test('drawer uses a generated opaque background and native modal controls', async () => {
  const postcss = require('postcss');
  const tailwind = require('tailwindcss');
  const { default: config } = await import('../tailwind.config.js');
  const source = readFileSync(path.join(frontend, 'src/features/clean/CandidateDrawer.tsx'), 'utf8');
  const { css } = await postcss([tailwind({
    ...config,
    content: [{ raw: source, extension: 'tsx' }],
  })]).process('@tailwind utilities;', { from: undefined });
  assert.match(css, /\.bg-archive-paper\s*\{[^}]*--tw-bg-opacity: 1;[^}]*background-color:/);
  assert.match(source, /<dialog[\s\S]*onCancel=/);
  assert.match(source, /dialog\.showModal\(\)/);
  assert.match(source, /opener\.focus\(\)/);
});

test('a local field edit clears the match while a no-op preserves it', () => {
  const { useWizardStore } = loadSource('src/store/wizardStore.ts', {
    zustand: require('zustand'),
    'zustand/middleware': { persist: init => init },
  });
  useWizardStore.getState().setResults([row('card.jpg', 'Original', manual)], 0);
  useWizardStore.getState().updateResultCell('card.jpg', field, 'Original');
  assert.equal(useWizardStore.getState().results[0].validation[field].reconciliation, manual);
  useWizardStore.getState().updateResultCell('card.jpg', field, '');
  const card = useWizardStore.getState().results[0];
  assert.equal(card.validation[field].reconciliation, null);
  assert.equal(card.data[field], 'Original');
  assert.equal(card.editedData[field], '');
});

test('auto-accept waits for persistence and an old column response cannot confirm', async () => {
  const renderPane = (postReconcile, onCellReconciled, notify) => {
    let unmount;
    const element = (type, props) => ({ type, props });
    const { ReconcilePane } = loadSource('src/features/clean/ReconcilePane.tsx', {
      'react/jsx-runtime': { jsx: element, jsxs: element },
      react: {
        useRef: current => ({ current }),
        useEffect: setup => { unmount = setup(); },
        useState: initial => [initial, () => {}],
      },
      sonner: { toast: { success: notify, info: notify } },
      'lucide-react': {},
      '../../api/batchesApi': { postReconcile },
      './validationRuntime': loadSource('src/features/clean/validationRuntime.ts', {}),
    });
    const tree = ReconcilePane({
      activeColumn: field, authorityType: 'gnd-persons', batchId: 'batch',
      displayRows: [{ ...row('card.jpg', 'Künstler'), _pageFilename: 'card.jpg' }],
      onCellReconciled,
    });
    function findRunButton(node) {
      if (node?.props?.id === 'clean-reconcile-run') return node;
      return [node?.props?.children].flat().map(child => child?.props && findRunButton(child)).find(Boolean);
    }
    return { run: findRunButton(tree).props.onClick, unmount };
  };

  const candidate = { label: 'Künstler', uri };
  let resolveSearch;
  let saveCalls = 0;
  const stale = renderPane(
    () => new Promise(resolve => { resolveSearch = resolve; }),
    async () => { saveCalls++; return true; },
    () => assert.fail('The old pane must not report success'),
  );
  stale.run();
  stale.unmount();
  resolveSearch({ candidates: [candidate] });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(saveCalls, 0);

  let finishSave;
  let message;
  const current = renderPane(async () => ({ candidates: [candidate] }), (...args) => {
    const [filename, name, outcome, source, expectedValue] = args;
    assert.deepEqual([filename, name, source, expectedValue], ['card.jpg', field, 'reconciliation-auto', 'Künstler']);
    assert.equal(outcome.uri, uri);
    assert.equal(outcome.picked_by, 'auto');
    return new Promise(resolve => { finishSave = resolve; });
  }, value => { message = value; });
  current.run();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(message, undefined);
  finishSave(false);
  await new Promise(resolve => setImmediate(resolve));
  assert.match(message, /Reconciled 0 cells automatically/);
});

for (const method of ['downloadCSV', 'downloadJSON', 'downloadLIDO', 'downloadEAD',
  'downloadDarwinCore', 'downloadDublinCore', 'downloadMARCXML', 'downloadMETSMODS']) {
  test(`${method} rechecks live rows, batch and write status at confirmation`, () => {
    const { useResultsExport, downloads, confirm } = exportHarness();
    const original = row('same.jpg', 'Original', manual);
    original.validation[field].status = 'invalid';
    let rows = [original];
    let batch = 'A';
    let status = 'ready';
    const api = useResultsExport('A', () => status === 'ready' ? [rows, [field], batch] : null);
    api[method]();
    rows = [{ ...row('same.jpg', 'Original', null), editedData: { [field]: 'Changed' } }];
    for (const blocked of ['pending', 'failed']) {
      status = blocked;
      confirm();
      assert.equal(downloads.length, 0);
    }
    status = 'ready';
    batch = 'B';
    confirm();
    assert.equal(downloads.length, 0);
    batch = 'A';
    confirm();
    assert.equal(downloads.length, 1);
    assert.ok(!downloads[0].includes(uri));
    if (method === 'downloadCSV' || method === 'downloadJSON') {
      assert.match(downloads[0], /Original/);
      assert.match(downloads[0], /Changed/);
    }
  });
}

test('batch revisions reject delayed hydration and isolate identical filenames on revisits', () => {
  const { useWizardStore } = loadSource('src/store/wizardStore.ts', {
    zustand: require('zustand'),
    'zustand/middleware': { persist: init => init },
  });
  const state = useWizardStore.getState;
  state().setCockpitSplitPercent(61);
  state().loadBatchForReview('A');
  const firstA = state().batchRevision;
  const a = { ...row('same.jpg', 'OCR A', manual), editedData: { [field]: 'Edited A' } };
  const b = { ...row('same.jpg', 'OCR B', { ...automatic, uri: uri + '-b' }), editedData: { [field]: 'Edited B' } };
  state().setResults([a], firstA);
  state().loadBatchForReview('B');
  const revisionB = state().batchRevision;
  assert.equal(state().results.length, 0);
  state().setResults([a], firstA);
  assert.equal(state().results.length, 0);
  state().setResults([b], revisionB);
  assert.equal(state().results[0], b);
  state().setBatchId('A');
  state().setResults([b], revisionB);
  state().setResults([a], firstA);
  assert.equal(state().results.length, 0);
  state().setResults([a], state().batchRevision);
  assert.equal(state().results[0], a);
  assert.equal(state().cockpitSplitPercent, 61);
});

test('Undo keeps failed rows, ignores a duplicate click and removes successful rows', async () => {
  const slots = [];
  let cursor = 0;
  const { useCleanState } = loadSource('src/features/clean/useCleanState.ts', {
    react: {
      useCallback: fn => fn,
      useState: initial => {
        const index = cursor++;
        if (!(index in slots)) slots[index] = initial;
        return [slots[index], value => { slots[index] = typeof value === 'function' ? value(slots[index]) : value; }];
      },
      useRef: current => {
        const index = cursor++;
        return slots[index] ??= { current };
      },
    },
  });
  const render = () => { cursor = 0; return useCleanState(); };
  render().pushUndo({ id: 'undo', cellSnapshot: new Map([['ok.jpg', {}], ['retry.jpg', {}]]) });
  let finish;
  const pending = render().runUndo('undo', () => new Promise(resolve => { finish = resolve; }));
  assert.equal(render().undoStack.length, 1);
  assert.equal(render().undoBusy, true);
  await render().runUndo('undo', () => assert.fail('duplicate write'));
  finish(['retry.jpg']);
  await pending;
  assert.deepEqual([...render().undoStack[0].cellSnapshot.keys()], ['retry.jpg']);
  await render().runUndo('undo', async entry => {
    assert.deepEqual([...entry.cellSnapshot.keys()], ['retry.jpg']);
    return [];
  });
  assert.equal(render().undoStack.length, 0);
});

test('Results edits retain their original preconditions, surface failure and retry the same draft', async () => {
  const axes = [];
  let response;
  const invalidations = [];
  const session = { batchId: 'batch', batchRevision: 1 };
  const store = Object.assign(select => select(session), { getState: () => session });
  let stateSlot = 0;
  const states = [];
  const component = Symbol('EditableCell');
  const react = {
    Fragment: Symbol('Fragment'),
    useMemo: fn => fn(),
    useState: initial => {
      const slot = stateSlot++;
      if (!(slot in states)) states[slot] = initial;
      return [states[slot], value => { states[slot] = typeof value === 'function' ? value(states[slot]) : value; }];
    },
  };
  const jsx = (type, props) => ({ type, props });
  const { ResultsTable } = loadSource('src/features/results/ResultsTable.tsx', {
    react: { ...react, default: react },
    'react/jsx-runtime': { jsx, jsxs: jsx },
    '@tanstack/react-table': {
      createColumnHelper: () => ({
        accessor: (_key, options) => options,
        display: options => options,
      }),
      getCoreRowModel() {},
      getSortedRowModel() {},
      useReactTable: ({ columns }) => ({
        getHeaderGroups: () => [],
        getRowModel: () => ({ rows: [] }),
        getColumn: () => undefined,
        extraction: axes.push(columns.find(column => column.id === 'extraction')),
      }),
    },
    '@tanstack/react-query': { useQueryClient: () => ({ invalidateQueries: async options => invalidations.push(options) }) },
    axios: { isAxiosError: error => !!error.response },
    '../../api/batchesApi': {
      ResultEditVerificationError: class extends Error {},
      useSyncedResultPatch: () => async (...args) => response(...args),
    },
    'lucide-react': {},
    'yet-another-react-lightbox': {},
    '../../store/wizardStore': { useWizardStore: store },
    './ThumbnailCell': {},
    './ValidationBadge': {},
    './EditableCell': { EditableCell: component },
    './expandResults': { expandResults: rows => rows },
    './groupValue': loadSource('src/features/results/groupValue.ts', {}),
    './confidence': {},
  });
  const source = { ...row('card.jpg', 'original', manual), editedData: { [field]: 'confirmed' } };
  function render(candidate = source, groups = {}) {
    stateSlot = 0;
    ResultsTable({ results: [candidate], fields: [field], fieldGroups: groups, configReady: true, batchName: 'batch' });
    const result = axes.at(-1).cell({ row: { original: candidate } });
    function flatten(node) {
      if (!node || typeof node !== 'object') return [];
      if (Array.isArray(node)) return node.flatMap(flatten);
      return [node, ...flatten(node.props?.children)];
    }
    return flatten(result);
  }

  let attempt;
  response = async (...args) => {
    attempt = args;
    throw new Error('write failed');
  };
  const editor = render().find(node => node.type === component);
  editor.props.onCommit('draft');
  await new Promise(setImmediate);
  let nodes = render();
  assert.equal(nodes.find(node => node.type === component).props.value, 'confirmed');
  assert.equal(nodes.find(node => node.props.role === 'alert').props.children[0], 'Edit not saved.');
  assert.equal(attempt[2].expected_value, 'confirmed');
  assert.equal(attempt[2].expected_reconciliation, manual);

  response = async (...args) => {
    assert.deepEqual(args, attempt);
    throw { response: { status: 409 } };
  };
  nodes.find(node => node.type === 'button' && node.props.children === 'Retry save').props.onClick();
  await new Promise(setImmediate);
  nodes = render();
  assert.equal(invalidations.length, 1);
  assert.deepEqual(Array.from(invalidations[0].queryKey), ['results', 'batch']);
  assert.equal(nodes.find(node => node.props.role === 'alert').props.children[0], 'Edit not saved. Review the current field before editing again.');
  assert.equal(nodes.some(node => node.type === 'button' && node.props.children === 'Retry save'), false);

  for (const [candidate, groups] of [
    [{ ...source, _entryLabel: '1 / 2' }, {}],
    [{ ...source, data: { ...source.data, _entries: 'malformed' } }, {}],
    [source, { [field]: { fields: ['Name'], max_items: 2 } }],
  ]) assert.equal(render(candidate, groups).some(node => node.type === component), false);
});

test('lost Results PATCH responses verify value and match under the batch write lock', async () => {
  const client = new QueryClient();
  const filename = 'card.jpg';
  const baseline = { filename, data: { [field]: 'OCR' }, validation: { [field]: { reconciliation: manual } } };
  const saved = { ...baseline, edited_data: { [field]: 'Saved' }, validation: { [field]: { reconciliation: null } } };
  const snapshots = new Map();
  const writes = [];
  const reads = [];
  const { useSyncedResultPatch, resultWriteStatus } = loadSource('src/api/batchesApi.ts', {
    axios: { default: {
      isAxiosError: error => error.name === 'AxiosError',
      patch: async (url, payload) => {
        writes.push({ url, payload });
        throw Object.assign(new Error('Connection reset'), { name: 'AxiosError' });
      },
      get: async (url, config) => {
        reads.push(url);
        assert.equal(config.headers['Cache-Control'], 'no-cache');
        const snapshot = snapshots.get(url);
        if (!snapshot) throw new Error('Server unavailable');
        return { data: { results: [await snapshot], audit: [] } };
      },
    } },
    react: { useCallback: fn => fn },
    '@tanstack/react-query': {
      useQueryClient: () => client,
      useMutation: options => ({
        mutateAsync: args => client.getMutationCache().build(client, options).execute(args),
      }),
    },
    sonner: {},
  });
  const patch = useSyncedResultPatch();
  const request = { field, value: 'Saved', expected_value: 'OCR', expected_reconciliation: manual };

  for (const batch of ['committed', 'unavailable', 'different-value', 'different-match', 'other-batch']) {
    client.setQueryData(['results', batch], { results: [baseline], audit: [] });
  }

  let completeVerification;
  snapshots.set('/api/v1/batches/committed/results', new Promise(resolve => { completeVerification = resolve; }));
  const verifying = patch('committed', filename, request, undefined, 'verify-on-transport-error');
  assert.equal(resultWriteStatus(client, 'committed'), 'pending');
  assert.equal(resultWriteStatus(client, 'other-batch'), 'ready');
  assert.equal(client.getQueryData(['results', 'other-batch']).results[0], baseline);
  completeVerification(saved);
  assert.equal(await verifying, saved);
  assert.equal(resultWriteStatus(client, 'committed'), 'ready');
  assert.equal(client.getQueryData(['results', 'committed']).results[0], saved);
  assert.equal(client.getQueryData(['results', 'other-batch']).results[0], baseline);
  assert.deepEqual(reads, ['/api/v1/batches/committed/results']);

  for (const [batch, confirmed] of [
    ['different-value', baseline],
    ['different-match', { ...saved, validation: { [field]: { reconciliation: automatic } } }],
  ]) {
    snapshots.set(`/api/v1/batches/${batch}/results`, confirmed);
    await assert.rejects(patch(batch, filename, request, undefined, 'verify-on-transport-error'), { status: 'conflict' });
    assert.equal(client.getQueryData(['results', batch]).results[0], confirmed);
    assert.equal(resultWriteStatus(client, batch), 'failed');
  }

  await assert.rejects(patch('unavailable', filename, request, undefined, 'verify-on-transport-error'), { status: 'unresolved' });
  assert.equal(resultWriteStatus(client, 'unavailable'), 'failed');
  assert.equal(client.getQueryData(['results', 'unavailable']).results[0], baseline);
  await assert.rejects(patch('unavailable', filename, request, undefined, 'verify-only'), { status: 'unresolved' });
  snapshots.set('/api/v1/batches/unavailable/results', saved);
  assert.equal(await patch('unavailable', filename, request, undefined, 'verify-only'), saved);
  assert.equal(resultWriteStatus(client, 'unavailable'), 'ready');
  assert.equal(resultWriteStatus(client, 'different-match'), 'failed');
  assert.equal(writes.length, 4);
  for (const { payload } of writes) {
    assert.equal(payload.expected_value, 'OCR');
    assert.equal(payload.expected_reconciliation, manual);
  }
});
