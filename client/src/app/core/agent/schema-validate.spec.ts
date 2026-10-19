import { validateAgainstSchema, withDefaults } from './schema-validate';
import { JsonSchema } from './ui-tool.types';

const SCHEMA: JsonSchema = {
  type: 'object',
  additionalProperties: false,
  required: ['route'],
  properties: {
    route: { type: 'string', enum: ['/', '/stats'] },
    limit: { type: 'integer', minimum: 1, maximum: 200, default: 50 },
    mode: { type: ['string', 'null'], default: 'replace' },
    paths: { type: 'array', items: { type: 'string' }, maxItems: 2 },
    query: { type: 'object', additionalProperties: { type: ['string', 'number'] } },
  },
};

describe('validateAgainstSchema', () => {
  it('accepts a valid value', () => {
    expect(validateAgainstSchema(SCHEMA, { route: '/', limit: 3, mode: null, paths: ['a'] })).toEqual([]);
  });

  it('reports type, enum, range, required, unknown-property and item errors', () => {
    expect(validateAgainstSchema(SCHEMA, {})).toEqual(['args.route: required']);
    expect(validateAgainstSchema(SCHEMA, { route: '/x' })[0]).toContain('must be one of');
    expect(validateAgainstSchema(SCHEMA, { route: '/', limit: 1.5 })[0]).toContain('expected integer');
    expect(validateAgainstSchema(SCHEMA, { route: '/', limit: 500 })[0]).toContain('above 200');
    expect(validateAgainstSchema(SCHEMA, { route: '/', extra: 1 })[0]).toContain('unknown property');
    expect(validateAgainstSchema(SCHEMA, { route: '/', paths: ['a', 2, 'c'] })).toHaveLength(2);
    expect(validateAgainstSchema(SCHEMA, { route: '/', query: { a: true } })[0]).toContain('args.query.a');
  });

  it('fills top-level defaults without overriding given values', () => {
    expect(withDefaults(SCHEMA, { route: '/', limit: 7 })).toEqual({ route: '/', limit: 7, mode: 'replace' });
  });

  it('ignores Object.prototype names: they are neither declared properties nor present keys', () => {
    expect(validateAgainstSchema(SCHEMA, JSON.parse('{"route":"/","constructor":1}'))).not.toEqual([]);
    expect(validateAgainstSchema(SCHEMA, JSON.parse('{"route":"/","hasOwnProperty":"x"}'))).not.toEqual([]);
    expect(validateAgainstSchema({ type: 'object', required: ['toString'], properties: {} }, {})).not.toEqual([]);
    const filled = withDefaults({ properties: { constructor: { type: 'string', default: 'd' } } }, {});
    expect(Object.hasOwn(filled, 'constructor')).toBe(true);
  });
});
