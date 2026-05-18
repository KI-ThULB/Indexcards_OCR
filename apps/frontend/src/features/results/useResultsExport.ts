import { toast } from 'sonner';
import type { ResultRow } from '../../store/wizardStore';

// ── Helpers ──────────────────────────────────────────────────────────────────

function escapeXml(str: string): string {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}

function fieldValue(row: ResultRow, field: string): string {
  const edited = row.editedData[field];
  return edited !== undefined ? edited : (row.data[field] ?? '');
}

function triggerDownload(content: string, filename: string, mime: string) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// ── Hook ─────────────────────────────────────────────────────────────────────

export function useResultsExport(results: ResultRow[], fields: string[], batchName: string) {

  // ── Validation gate ────────────────────────────────────────────────────────
  // Soft-block: shows a sonner warning toast when any row has open invalid status.
  // Curator can confirm (Export anyway) or cancel. Corrected proposals are NOT
  // counted — only status === 'invalid' triggers the gate.
  function checkValidationGate(onProceed: () => void): void {
    const invalidCount = results.filter((r) =>
      r.validation && Object.values(r.validation).some((v) => v.status === 'invalid')
    ).length;

    if (invalidCount === 0) {
      onProceed();
      return;
    }

    toast.warning(`${invalidCount} row${invalidCount === 1 ? '' : 's'} have validation issues.`, {
      description: 'Export will proceed if you confirm.',
      action: { label: 'Export anyway', onClick: onProceed },
      cancel: { label: 'Cancel', onClick: () => {} },
      duration: 10000,
    });
  }

  // ── CSV ────────────────────────────────────────────────────────────────────
  const downloadCSV = () => checkValidationGate(() => {
    const headers = [
      'File', 'Status', 'Error', 'Duration(s)',
      ...fields.flatMap((f) => [`${f}_ocr`, `${f}_edited`]),
    ];
    const rows: string[][] = [];
    results.forEach((row) => {
      const entriesJson = row.data['_entries'];
      if (row.status === 'success' && entriesJson) {
        // Multi-entry page (e.g. Findmittel): expand each entry into its own CSV row
        try {
          const entries = JSON.parse(entriesJson) as Record<string, string>[];
          entries.forEach((entry) => {
            rows.push([
              row.filename,
              row.status,
              row.error ?? '',
              row.duration.toFixed(2),
              ...fields.flatMap((f) => [entry[f] ?? '', '']),
            ]);
          });
          return;
        } catch { /* fall through to single-row handling */ }
      }
      rows.push([
        row.filename,
        row.status,
        row.error ?? '',
        row.duration.toFixed(2),
        ...fields.flatMap((f) => [row.data[f] ?? '', row.editedData[f] ?? '']),
      ]);
    });
    const csv = [headers, ...rows]
      .map((r) => r.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(','))
      .join('\r\n');
    // UTF-8 BOM for Excel compatibility
    triggerDownload('\uFEFF' + csv, `${batchName}_results.csv`, 'text/csv;charset=utf-8');
  });

  // ── JSON ───────────────────────────────────────────────────────────────────
  const downloadJSON = () => checkValidationGate(() => {
    const payload: object[] = [];
    results.forEach((row) => {
      const entriesJson = row.data['_entries'];
      if (row.status === 'success' && entriesJson) {
        // Multi-entry page (e.g. Findmittel): expand each entry into its own JSON record
        try {
          const entries = JSON.parse(entriesJson) as Record<string, string>[];
          entries.forEach((entry) => {
            payload.push({
              filename: row.filename,
              status: row.status,
              error: row.error ?? null,
              duration: row.duration,
              fields: Object.fromEntries(fields.map((f) => [f, { ocr: entry[f] ?? '' }])),
            });
          });
          return;
        } catch { /* fall through to single-record handling */ }
      }
      payload.push({
        filename: row.filename,
        status: row.status,
        error: row.error ?? null,
        duration: row.duration,
        fields: Object.fromEntries(
          fields.map((f) => [
            f,
            { ocr: row.data[f] ?? '', ...(row.editedData[f] !== undefined ? { edited: row.editedData[f] } : {}) },
          ])
        ),
      });
    });
    triggerDownload(JSON.stringify(payload, null, 2), `${batchName}_results.json`, 'application/json');
  });

  // ── LIDO-XML 1.1 ──────────────────────────────────────────────────────────
  const downloadLIDO = () => checkValidationGate(() => {
    const e = escapeXml;
    const successful = results.filter((r) => r.status === 'success');

    const records = successful.map((row) => {
      const get = (f: string) => fieldValue(row, f);
      const titel     = get('Titel') || row.filename;
      const bestellNr = get('Bestellnummer') || get('Bestell-Nr.');
      const komponist = get('Komponist');
      const datum     = get('Datum');
      const ort       = get('Ort der Aufnahme') || get('Ort der Aufnahme Datum');

      const descSets = fields
        .map((f) => ({ name: f, value: get(f) }))
        .filter((f) => f.value)
        .map((f) => `
          <lido:objectDescriptionSet lido:type="${e(f.name)}">
            <lido:descriptiveNoteValue>${e(f.value)}</lido:descriptiveNoteValue>
          </lido:objectDescriptionSet>`)
        .join('');

      const actorBlock = komponist
        ? `<lido:eventActor>
              <lido:actorInEvent>
                <lido:actor>
                  <lido:nameActorSet>
                    <lido:appellationValue>${e(komponist)}</lido:appellationValue>
                  </lido:nameActorSet>
                </lido:actor>
                <lido:roleActor><lido:term>Komponist</lido:term></lido:roleActor>
              </lido:actorInEvent>
            </lido:eventActor>`
        : '';

      const eventBlock = (komponist || datum || ort)
        ? `<lido:eventWrap>
          <lido:eventSet>
            <lido:event>
              <lido:eventType><lido:term>Recording</lido:term></lido:eventType>
              ${actorBlock}
              ${datum ? `<lido:eventDate><lido:displayDate>${e(datum)}</lido:displayDate></lido:eventDate>` : ''}
              ${ort ? `<lido:eventPlace><lido:place><lido:namePlaceSet><lido:appellationValue>${e(ort)}</lido:appellationValue></lido:namePlaceSet></lido:place></lido:eventPlace>` : ''}
            </lido:event>
          </lido:eventSet>
        </lido:eventWrap>`
        : '';

      return `  <lido:lido>
    <lido:lidoRecID lido:type="local">${e(row.filename)}</lido:lidoRecID>
    <lido:descriptiveMetadata xml:lang="de">
      <lido:objectClassificationWrap>
        <lido:classificationWrap>
          <lido:classification lido:type="object type">
            <lido:term>Karteikarte</lido:term>
          </lido:classification>
        </lido:classificationWrap>
      </lido:objectClassificationWrap>
      <lido:objectIdentificationWrap>
        <lido:titleWrap>
          <lido:titleSet>
            <lido:appellationValue xml:lang="de">${e(titel)}</lido:appellationValue>
          </lido:titleSet>
        </lido:titleWrap>
        ${bestellNr ? `<lido:repositoryWrap>
          <lido:repositorySet>
            <lido:workID lido:type="inventory number">${e(bestellNr)}</lido:workID>
          </lido:repositorySet>
        </lido:repositoryWrap>` : ''}
        <lido:objectDescriptionWrap>${descSets}
        </lido:objectDescriptionWrap>
      </lido:objectIdentificationWrap>
      ${eventBlock}
    </lido:descriptiveMetadata>
    <lido:administrativeMetadata xml:lang="de">
      <lido:recordWrap>
        <lido:recordID lido:type="local">${e(row.filename)}</lido:recordID>
        <lido:recordType><lido:term>item</lido:term></lido:recordType>
        <lido:recordSource>
          <lido:legalBodyName>
            <lido:appellationValue>${e(batchName)}</lido:appellationValue>
          </lido:legalBodyName>
        </lido:recordSource>
      </lido:recordWrap>
    </lido:administrativeMetadata>
  </lido:lido>`;
    });

    const xml = `<?xml version="1.0" encoding="UTF-8"?>
<lido:lidoWrap
  xmlns:lido="http://www.lido-schema.org"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xsi:schemaLocation="http://www.lido-schema.org http://www.lido-schema.org/schema/v1.1/lido-v1.1.xsd">
${records.join('\n')}
</lido:lidoWrap>`;
    triggerDownload(xml, `${batchName}_lido.xml`, 'application/xml;charset=utf-8');
  });

  // ── EAD ───────────────────────────────────────────────────────────────────
  const downloadEAD = () => checkValidationGate(() => {
    const e = escapeXml;
    const skipInDid = new Set(['Titel', 'Bestellnummer', 'Bestell-Nr.', 'Spieldauer', 'Ort der Aufnahme', 'Ort der Aufnahme Datum', 'Datum']);

    const components = results
      .filter((r) => r.status === 'success')
      .map((row) => {
        const get = (f: string) => fieldValue(row, f);
        const titel     = get('Titel') || row.filename;
        const bestellNr = get('Bestellnummer') || get('Bestell-Nr.');
        const datum     = get('Datum');
        const spieldauer = get('Spieldauer');
        const ort       = get('Ort der Aufnahme') || get('Ort der Aufnahme Datum');

        const oddParts = fields
          .filter((f) => !skipInDid.has(f))
          .map((f) => ({ name: f, value: get(f) }))
          .filter((f) => f.value)
          .map((f) => `${e(f.name)}: ${e(f.value)}`);

        return `      <c level="item">
        <did>
          <unittitle>${e(titel)}</unittitle>
          ${bestellNr ? `<unitid>${e(bestellNr)}</unitid>` : ''}
          ${datum ? `<unitdate>${e(datum)}</unitdate>` : ''}
          ${spieldauer ? `<physdesc><extent>${e(spieldauer)}</extent></physdesc>` : ''}
          ${ort ? `<physloc>${e(ort)}</physloc>` : ''}
          <dao href="/batches-static/${e(batchName)}/${e(row.filename)}" title="${e(titel)}" />
        </did>
        ${oddParts.length > 0 ? `<odd><p>${oddParts.join(' | ')}</p></odd>` : ''}
      </c>`;
      });

    const xml = `<?xml version="1.0" encoding="UTF-8"?>
<ead xmlns="urn:isbn:1-931666-22-9"
     xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
     xsi:schemaLocation="urn:isbn:1-931666-22-9 http://www.loc.gov/ead/ead.xsd">
  <eadheader>
    <eadid>${e(batchName)}</eadid>
    <filedesc>
      <titlestmt>
        <titleproper>Archival Finding Aid: ${e(batchName)}</titleproper>
      </titlestmt>
    </filedesc>
  </eadheader>
  <archdesc level="collection">
    <did>
      <unittitle>${e(batchName)}</unittitle>
    </did>
    <dsc type="combined">
${components.join('\n')}
    </dsc>
  </archdesc>
</ead>`;
    triggerDownload(xml, `${batchName}_ead.xml`, 'application/xml;charset=utf-8');
  });

  // ── Darwin Core (Simple Darwin Record) ────────────────────────────────────
  const downloadDarwinCore = () => checkValidationGate(() => {
    const e = escapeXml;

    // Known DwC term mappings
    const dwcMap: Record<string, string> = {
      'Titel':                  'dc:title',
      'Komponist':              'dwc:recordedBy',
      'Datum':                  'dwc:eventDate',
      'Ort der Aufnahme':       'dwc:locality',
      'Ort der Aufnahme Datum': 'dwc:locality',
      'Bestellnummer':          'dwc:catalogNumber',
      'Bestell-Nr.':            'dwc:otherCatalogNumbers',
      'Ton-Ingenieur':          'dwc:identifiedBy',
    };

    const records = results
      .filter((r) => r.status === 'success')
      .map((row) => {
        const get = (f: string) => fieldValue(row, f);
        const mapped = new Set<string>();

        const mappedLines = Object.entries(dwcMap)
          .map(([field, term]) => {
            const val = get(field);
            if (val) { mapped.add(field); return `    <${term}>${e(val)}</${term}>`; }
            return '';
          })
          .filter(Boolean);

        const remaining = fields
          .filter((f) => !mapped.has(f))
          .map((f) => ({ name: f, value: get(f) }))
          .filter((f) => f.value);

        const dynProps = remaining.length > 0
          ? e(JSON.stringify(Object.fromEntries(remaining.map((f) => [f.name, f.value]))))
          : '';

        return `  <dwr:SimpleDarwinRecord>
    <dwc:occurrenceID>${e(row.filename)}</dwc:occurrenceID>
    <dwc:collectionCode>${e(batchName)}</dwc:collectionCode>
    <dwc:basisOfRecord>PreservedSpecimen</dwc:basisOfRecord>
${mappedLines.join('\n')}
    ${dynProps ? `<dwc:dynamicProperties>${dynProps}</dwc:dynamicProperties>` : ''}
  </dwr:SimpleDarwinRecord>`;
      });

    const xml = `<?xml version="1.0" encoding="UTF-8"?>
<dwr:SimpleDarwinRecordSet
  xmlns:dwr="http://rs.tdwg.org/dwc/xsd/simpledarwincore/"
  xmlns:dwc="http://rs.tdwg.org/dwc/terms/"
  xmlns:dc="http://purl.org/dc/terms/"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xsi:schemaLocation="http://rs.tdwg.org/dwc/xsd/simpledarwincore/ http://rs.tdwg.org/dwc/xsd/tdwg_dwc_simple.xsd">
${records.join('\n')}
</dwr:SimpleDarwinRecordSet>`;
    triggerDownload(xml, `${batchName}_darwincore.xml`, 'application/xml;charset=utf-8');
  });

  // ── Dublin Core (OAI-DC) ──────────────────────────────────────────────────
  const downloadDublinCore = () => checkValidationGate(() => {
    const e = escapeXml;

    // DC element mappings (first match wins per field)
    const dcMap: Record<string, string> = {
      'Titel':              'dc:title',
      'Titel und Spieldauer': 'dc:title',
      'Komponist':          'dc:creator',
      'Textdichter':        'dc:contributor',
      'Bearbeiter':         'dc:contributor',
      'Dirigent':           'dc:contributor',
      'Chor-Dirigent':      'dc:contributor',
      'Solisten':           'dc:contributor',
      'Solisten (Rückseite)': 'dc:contributor',
      'Orchester':          'dc:contributor',
      'Datum':              'dc:date',
      'Bestellnummer':      'dc:identifier',
      'Bestell-Nr.':        'dc:identifier',
      'Matrizen-Nr.':       'dc:identifier',
      'Verlag':             'dc:publisher',
      'Ort der Aufnahme':   'dc:coverage',
      'Ort der Aufnahme Datum': 'dc:coverage',
      'Form':               'dc:type',
      'Sperrvermerk':       'dc:rights',
      'Sperr-Vermerke':     'dc:rights',
      'Sprache':            'dc:language',
      'Bemerkungen':        'dc:description',
    };

    const records = results
      .filter((r) => r.status === 'success')
      .map((row) => {
        const get = (f: string) => fieldValue(row, f);
        const mapped = new Set<string>();

        const lines: string[] = [`    <dc:identifier>${e(row.filename)}</dc:identifier>`];

        for (const [field, term] of Object.entries(dcMap)) {
          const val = get(field);
          if (val) { mapped.add(field); lines.push(`    <${term}>${e(val)}</${term}>`); }
        }

        const rest = fields
          .filter((f) => !mapped.has(f))
          .map((f) => ({ name: f, value: get(f) }))
          .filter((f) => f.value)
          .map((f) => `${f.name}: ${f.value}`)
          .join('; ');

        if (rest) lines.push(`    <dc:description>${e(rest)}</dc:description>`);
        lines.push(`    <dc:source>${e(batchName)}</dc:source>`);
        lines.push(`    <dc:type>Sound</dc:type>`);
        lines.push(`    <dc:format>audio/x-tape-archive-card</dc:format>`);

        return `  <oai_dc:dc>
${lines.join('\n')}
  </oai_dc:dc>`;
      });

    const xml = `<?xml version="1.0" encoding="UTF-8"?>
<records
  xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/"
  xmlns:dc="http://purl.org/dc/elements/1.1/"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xsi:schemaLocation="http://www.openarchives.org/OAI/2.0/oai_dc/ http://www.openarchives.org/OAI/2.0/oai_dc.xsd">
${records.join('\n')}
</records>`;
    triggerDownload(xml, `${batchName}_dublincore.xml`, 'application/xml;charset=utf-8');
  });

  // ── MARC21-XML (MARCXML) ──────────────────────────────────────────────────
  const downloadMARCXML = () => checkValidationGate(() => {
    const e = escapeXml;

    const buildRecord = (entry: Record<string, string>, sourceFile: string, idx?: number): string => {
      const nr     = entry['Nr.'] || (idx !== undefined ? String(idx + 1) : '');
      const name   = entry['Zu- u. Vorname'] || '';
      const titel  = entry['Titel der Habilitationsschrift:']
                  || entry['Titel der Dissertation:']
                  || entry['Titel'] || '';
      // K10plus normalized $d term for field 4204 / MARC21 502 $b
      const thesisType = entry['Titel der Habilitationsschrift:']
                  ? 'Habilitationsschrift'
                  : entry['Titel der Dissertation:']
                  ? 'Dissertation'
                  : 'Habilitationsschrift';
      const jahr   = (entry['Jahr'] || '').match(/\d{4}/)?.[0] ?? '';
      const gutachterRaw = entry['Gutachter'] || '';

      const today = new Date().toISOString().slice(2, 8).replace(/-/g, '');
      const year4 = jahr.padEnd(4, ' ').slice(0, 4);
      const field008 = `${today}s${year4}    gw           000 0 ger d`;

      const recId = `${sourceFile}${nr ? '_' + nr : idx !== undefined ? '_' + (idx + 1) : ''}`;

      const f099 = nr
        ? `    <marc:datafield tag="099" ind1=" " ind2=" ">
      <marc:subfield code="a">${e(nr)}</marc:subfield>
    </marc:datafield>`
        : '';

      // K10plus 3000 → MARC21 100: personal name (VerfasserIn, gender-neutral per K10plus convention)
      const f100 = name
        ? `    <marc:datafield tag="100" ind1="1" ind2=" ">
      <marc:subfield code="a">${e(name)}</marc:subfield>
      <marc:subfield code="e">VerfasserIn</marc:subfield>
      <marc:subfield code="4">aut</marc:subfield>
    </marc:datafield>`
        : '';

      // K10plus 4000 → MARC21 245: title ($a) + responsibility statement ($c)
      const f245 = titel
        ? `    <marc:datafield tag="245" ind1="${name ? '1' : '0'}" ind2="0">
      <marc:subfield code="a">${e(titel)}</marc:subfield>
      ${name ? `<marc:subfield code="c">${e(name)}</marc:subfield>` : ''}
    </marc:datafield>`
        : '';

      // K10plus 4030 → MARC21 264: place of production (ind2=0 for unpublished thesis)
      const f264 = `    <marc:datafield tag="264" ind1=" " ind2="0">
      <marc:subfield code="a">Jena</marc:subfield>
      <marc:subfield code="b">Friedrich-Schiller-Universität Jena</marc:subfield>
      ${jahr ? `<marc:subfield code="c">${e(jahr)}</marc:subfield>` : ''}
    </marc:datafield>`;

      // K10plus 0501/0502/0503 → MARC21 336/337/338: RDA content/media/carrier type
      const rdaFields = `    <marc:datafield tag="336" ind1=" " ind2=" ">
      <marc:subfield code="a">Text</marc:subfield>
      <marc:subfield code="b">txt</marc:subfield>
      <marc:subfield code="2">rdacontent</marc:subfield>
    </marc:datafield>
    <marc:datafield tag="337" ind1=" " ind2=" ">
      <marc:subfield code="a">ohne Hilfsmittel zu benutzen</marc:subfield>
      <marc:subfield code="b">n</marc:subfield>
      <marc:subfield code="2">rdamedia</marc:subfield>
    </marc:datafield>
    <marc:datafield tag="338" ind1=" " ind2=" ">
      <marc:subfield code="a">Band</marc:subfield>
      <marc:subfield code="b">nc</marc:subfield>
      <marc:subfield code="2">rdacarrier</marc:subfield>
    </marc:datafield>`;

      // K10plus 4204 → MARC21 502: Hochschulschriftenvermerk
      // $b = Charakter (K10plus normalized term: "Dissertation" or "Habilitationsschrift"), $c = Institution, $d = Jahr
      const f502 = `    <marc:datafield tag="502" ind1=" " ind2=" ">
      <marc:subfield code="b">${e(thesisType)}</marc:subfield>
      <marc:subfield code="c">Friedrich-Schiller-Universität Jena</marc:subfield>
      ${jahr ? `<marc:subfield code="d">${e(jahr)}</marc:subfield>` : ''}
    </marc:datafield>`;

      const f500 = `    <marc:datafield tag="500" ind1=" " ind2=" ">
      <marc:subfield code="a">Retrokonversion aus handschriftlichem Findmittel (ThULB Jena). Quellseite: ${e(sourceFile)}</marc:subfield>
    </marc:datafield>`;

      // K10plus 1131 → MARC21 655: Art des Inhalts "Hochschulschrift" (mandatory in K10plus)
      // GND authority: PPN 105825778 / ID gnd/4113937-9
      const f655 = `    <marc:datafield tag="655" ind1=" " ind2="7">
      <marc:subfield code="a">Hochschulschrift</marc:subfield>
      <marc:subfield code="0">(DE-588)4113937-9</marc:subfield>
      <marc:subfield code="2">gnd</marc:subfield>
    </marc:datafield>`;

      const gutachterList = gutachterRaw
        ? gutachterRaw.split(/\s*;\s*/).map((g) => g.trim()).filter(Boolean)
        : [];
      const f700s = gutachterList
        .map(
          (g) => `    <marc:datafield tag="700" ind1="1" ind2=" ">
      <marc:subfield code="a">${e(g)}</marc:subfield>
      <marc:subfield code="e">AkademischeR BetreuerIn</marc:subfield>
      <marc:subfield code="4">dgs</marc:subfield>
    </marc:datafield>`
        )
        .join('\n');

      // Field order follows MARC21 numeric sequence per K10plus convention
      return `  <marc:record>
    <marc:leader>00000nam a2200000 i 4500</marc:leader>
    <marc:controlfield tag="001">${e(recId)}</marc:controlfield>
    <marc:controlfield tag="003">DE-27</marc:controlfield>
    <marc:controlfield tag="008">${field008}</marc:controlfield>
    <marc:datafield tag="040" ind1=" " ind2=" ">
      <marc:subfield code="a">DE-27</marc:subfield>
      <marc:subfield code="b">ger</marc:subfield>
      <marc:subfield code="e">rda</marc:subfield>
    </marc:datafield>
    <marc:datafield tag="041" ind1="0" ind2=" ">
      <marc:subfield code="a">ger</marc:subfield>
    </marc:datafield>
    <marc:datafield tag="044" ind1=" " ind2=" ">
      <marc:subfield code="c">XA-DE</marc:subfield>
    </marc:datafield>
${f099}
${f100}
${f245}
${f264}
${rdaFields}
${f502}
${f500}
${f655}
${f700s}
  </marc:record>`;
    };

    const marcRecords: string[] = [];

    for (const row of results.filter((r) => r.status === 'success')) {
      const entriesJson = row.data['_entries'];
      if (entriesJson) {
        try {
          const entries = JSON.parse(entriesJson) as Record<string, string>[];
          entries.forEach((entry, idx) => marcRecords.push(buildRecord(entry, row.filename, idx)));
        } catch {
          marcRecords.push(buildRecord(row.data as Record<string, string>, row.filename));
        }
      } else {
        const entry = Object.fromEntries(fields.map((f) => [f, fieldValue(row, f)]));
        marcRecords.push(buildRecord(entry, row.filename));
      }
    }

    const xml = `<?xml version="1.0" encoding="UTF-8"?>
<!-- MARCXML-Export – Retrokonversion ThULB Jena / Batch: ${e(batchName)} -->
<!-- Hinweis: Vor dem Import in K10plus Datensätze durch Fachkräfte prüfen.   -->
<!-- GND-Normdaten, Signaturen und Pflichtfelder ggf. ergänzen.               -->
<marc:collection
  xmlns:marc="http://www.loc.gov/MARC21/slim"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xsi:schemaLocation="http://www.loc.gov/MARC21/slim http://www.loc.gov/standards/marcxml/schema/MARC21slim.xsd">
${marcRecords.join('\n')}
</marc:collection>`;

    triggerDownload(xml, `${batchName}_marc21.xml`, 'application/xml;charset=utf-8');
  });

  // ── METS/MODS ─────────────────────────────────────────────────────────────
  const downloadMETSMODS = () => checkValidationGate(() => {
    const e = escapeXml;

    const parseName = (nameStr: string): { family: string; given: string } => {
      const idx = nameStr.indexOf(',');
      return idx > 0
        ? { family: nameStr.slice(0, idx).trim(), given: nameStr.slice(idx + 1).trim() }
        : { family: nameStr.trim(), given: '' };
    };

    const buildMODS = (entry: Record<string, string>, sourceFile: string, dmdId: string): string => {
      const nr    = entry['Nr.'] || '';
      const name  = entry['Zu- u. Vorname'] || '';
      const titel = entry['Titel der Habilitationsschrift:']
                 || entry['Titel der Dissertation:']
                 || entry['Titel'] || '';
      const jahr  = (entry['Jahr'] || '').match(/\d{4}/)?.[0] ?? '';
      const gutachterRaw = entry['Gutachter'] || '';
      const schriftTyp = entry['Titel der Dissertation:'] ? 'Dissertation' : 'Habilitation';

      let autorBlock = '';
      if (name) {
        const { family, given } = parseName(name);
        autorBlock = `        <mods:name type="personal">
          <mods:namePart type="family">${e(family)}</mods:namePart>
          ${given ? `<mods:namePart type="given">${e(given)}</mods:namePart>` : ''}
          <mods:role>
            <mods:roleTerm type="code" authority="marcrelator">aut</mods:roleTerm>
          </mods:role>
        </mods:name>`;
      }

      const gutachterBlocks = gutachterRaw
        ? gutachterRaw.split(/\s*;\s*/).filter(Boolean).map((g) => {
            const { family, given } = parseName(g.trim());
            return `        <mods:name type="personal">
          <mods:namePart type="family">${e(family)}</mods:namePart>
          ${given ? `<mods:namePart type="given">${e(given)}</mods:namePart>` : ''}
          <mods:role>
            <mods:roleTerm type="code" authority="marcrelator">opn</mods:roleTerm>
          </mods:role>
        </mods:name>`;
          }).join('\n')
        : '';

      return `    <mets:dmdSec ID="${e(dmdId)}">
      <mets:mdWrap MDTYPE="MODS">
        <mets:xmlData>
          <mods:mods version="3.8" xmlns:mods="http://www.loc.gov/mods/v3">
        <mods:titleInfo>
          <mods:title>${e(titel)}</mods:title>
        </mods:titleInfo>
${autorBlock}
${gutachterBlocks}
        <mods:typeOfResource>text</mods:typeOfResource>
        <mods:genre authority="marcgt">thesis</mods:genre>
        <mods:originInfo eventType="production">
          <mods:place>
            <mods:placeTerm type="text">Jena</mods:placeTerm>
          </mods:place>
          <mods:publisher>Friedrich-Schiller-Universität Jena</mods:publisher>
          ${jahr ? `<mods:dateIssued encoding="iso8601">${e(jahr)}</mods:dateIssued>` : ''}
        </mods:originInfo>
        <mods:language>
          <mods:languageTerm type="code" authority="iso639-2b">ger</mods:languageTerm>
        </mods:language>
        ${nr ? `<mods:identifier type="local">${e(nr)}</mods:identifier>` : ''}
        ${(titel || jahr) ? `<mods:note type="thesis">${e(schriftTyp + (titel ? ', ' + titel : '') + (jahr ? ', Friedrich-Schiller-Universität Jena, ' + jahr : ''))}</mods:note>` : ''}
        <mods:note type="source">Retrokonversion aus handschriftlichem Findmittel (ThULB Jena). Quellseite: ${e(sourceFile)}</mods:note>
          </mods:mods>
        </mets:xmlData>
      </mets:mdWrap>
    </mets:dmdSec>`;
    };

    const buildGenericMODS = (row: ResultRow, dmdId: string): string => {
      const get = (f: string) => fieldValue(row, f);
      const titleFields   = ['Titel', 'Titel und Spieldauer', 'Tonband-Karteikarte'];
      const creatorFields = ['Komponist', 'Künstler'];
      const dateFields    = ['Datum', 'Jahr'];
      const idFields      = ['Bestellnummer', 'Bestell-Nr.', 'Inventar-Nr.', 'Nr.'];

      const titleVal   = titleFields.map(get).find(Boolean) || row.filename;
      const creatorVal = creatorFields.map(get).find(Boolean) || '';
      const dateVal    = dateFields.map(get).find(Boolean) || '';
      const idVal      = idFields.map(get).find(Boolean) || '';

      const usedFields = new Set([...titleFields, ...creatorFields, ...dateFields, ...idFields]);
      const noteLines  = fields
        .filter((f) => !usedFields.has(f))
        .map((f) => ({ name: f, value: get(f) }))
        .filter((f) => f.value)
        .map((f) => `        <mods:note type="local">${e(f.name + ': ' + f.value)}</mods:note>`)
        .join('\n');

      return `    <mets:dmdSec ID="${e(dmdId)}">
      <mets:mdWrap MDTYPE="MODS">
        <mets:xmlData>
          <mods:mods version="3.8" xmlns:mods="http://www.loc.gov/mods/v3">
        <mods:titleInfo><mods:title>${e(titleVal)}</mods:title></mods:titleInfo>
        ${creatorVal ? `<mods:name type="personal"><mods:namePart>${e(creatorVal)}</mods:namePart><mods:role><mods:roleTerm type="code" authority="marcrelator">cre</mods:roleTerm></mods:role></mods:name>` : ''}
        <mods:typeOfResource>still image</mods:typeOfResource>
        ${dateVal ? `<mods:originInfo><mods:dateCreated encoding="iso8601">${e(dateVal)}</mods:dateCreated></mods:originInfo>` : ''}
        <mods:identifier type="local">${e(idVal || row.filename)}</mods:identifier>
        <mods:location>
          <mods:url access="object in context">/batches-static/${e(batchName)}/${e(row.filename)}</mods:url>
        </mods:location>
${noteLines}
          </mods:mods>
        </mets:xmlData>
      </mets:mdWrap>
    </mets:dmdSec>`;
    };

    const dmdSections: string[]  = [];
    const fileEntries: string[]  = [];
    const structDivs: string[]   = [];
    let dmdCounter = 0;
    let fileCounter = 0;

    for (const row of results.filter((r) => r.status === 'success')) {
      fileCounter++;
      const fileId = `FILE_${String(fileCounter).padStart(4, '0')}`;
      fileEntries.push(
        `      <mets:file ID="${fileId}" MIMETYPE="image/jpeg">
        <mets:FLocat LOCTYPE="URL" xlink:href="/batches-static/${e(batchName)}/${e(row.filename)}"/>
      </mets:file>`
      );

      const entriesJson = row.data['_entries'];
      if (entriesJson) {
        try {
          const entries = JSON.parse(entriesJson) as Record<string, string>[];
          const pageDiv: string[] = [];
          for (const entry of entries) {
            dmdCounter++;
            const dmdId = `DMD_${String(dmdCounter).padStart(4, '0')}`;
            dmdSections.push(buildMODS(entry, row.filename, dmdId));
            pageDiv.push(`      <mets:div TYPE="document" DMDID="${dmdId}" LABEL="${e(entry['Zu- u. Vorname'] || dmdId)}">
        <mets:fptr FILEID="${fileId}"/>
      </mets:div>`);
          }
          structDivs.push(`      <mets:div TYPE="page" LABEL="${e(row.filename)}">\n${pageDiv.join('\n')}\n      </mets:div>`);
        } catch {
          dmdCounter++;
          const dmdId = `DMD_${String(dmdCounter).padStart(4, '0')}`;
          dmdSections.push(buildGenericMODS(row, dmdId));
          structDivs.push(`      <mets:div TYPE="document" DMDID="${dmdId}" LABEL="${e(row.filename)}"><mets:fptr FILEID="${fileId}"/></mets:div>`);
        }
      } else {
        dmdCounter++;
        const dmdId = `DMD_${String(dmdCounter).padStart(4, '0')}`;
        dmdSections.push(buildGenericMODS(row, dmdId));
        structDivs.push(`      <mets:div TYPE="document" DMDID="${dmdId}" LABEL="${e(row.filename)}"><mets:fptr FILEID="${fileId}"/></mets:div>`);
      }
    }

    const now = new Date().toISOString();
    const xml = `<?xml version="1.0" encoding="UTF-8"?>
<!-- METS/MODS-Export – ${e(batchName)} | Erstellt: ${now} -->
<!-- Hinweis: Vor Ingest in Goobi/Kitodo/DDB Daten prüfen und GND-Normdaten ergänzen. -->
<mets:mets
  xmlns:mets="http://www.loc.gov/METS/"
  xmlns:mods="http://www.loc.gov/mods/v3"
  xmlns:xlink="http://www.w3.org/1999/xlink"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xsi:schemaLocation="http://www.loc.gov/METS/ http://www.loc.gov/standards/mets/mets.xsd
                      http://www.loc.gov/mods/v3 http://www.loc.gov/standards/mods/v3/mods-3-8.xsd"
  OBJID="${e(batchName)}" TYPE="collection">

  <mets:metsHdr CREATEDATE="${now}">
    <mets:agent ROLE="CREATOR" TYPE="ORGANIZATION">
      <mets:name>ThULB Jena – Retrokonversion (Archival Metadata Extraction &amp; Export Tool)</mets:name>
    </mets:agent>
  </mets:metsHdr>

${dmdSections.join('\n')}

  <mets:fileSec>
    <mets:fileGrp USE="DEFAULT">
${fileEntries.join('\n')}
    </mets:fileGrp>
  </mets:fileSec>

  <mets:structMap TYPE="LOGICAL">
    <mets:div TYPE="collection" LABEL="${e(batchName)}">
${structDivs.join('\n')}
    </mets:div>
  </mets:structMap>

</mets:mets>`;

    triggerDownload(xml, `${batchName}_mets_mods.xml`, 'application/xml;charset=utf-8');
  });

  return { downloadCSV, downloadJSON, downloadLIDO, downloadEAD, downloadDarwinCore, downloadDublinCore, downloadMARCXML, downloadMETSMODS };
}
