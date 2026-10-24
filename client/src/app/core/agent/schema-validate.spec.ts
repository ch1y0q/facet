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
    expect(validateAgainstSchema(SCHEMA, JSON.parse('{"route":"/","constructor":1}'))).toEqual(['args.constructor: unknown property']);
    expect(validateAgainstSchema(SCHEMA, JSON.parse('{"route":"/","hasOwnProperty":"x"}'))).toEqual(['args.hasOwnProperty: unknown property']);
    expect(validateAgainstSchema({ type: 'object', required: ['toString'], properties: {} }, {})).toEqual(['args.toString: required']);
    const filled = withDefaults({ properties: { constructor: { type: 'string', default: 'd' } } }, {});
    expect(Object.hasOwn(filled, 'constructor')).toBe(true);
  });

  it('checks string length, array size, numeric minimum and type mixes with exact messages', () => {
    const schema: JsonSchema = {
      type: 'object',
      properties: {
        name: { type: 'string', minLength: 2, maxLength: 3 },
        tags: { type: 'array', minItems: 1 },
        score: { type: 'number', minimum: 0 },
        count: { type: 'integer' },
      },
    };
    expect(validateAgainstSchema(schema, { name: 'a' })).toEqual(['args.name: too short']);
    expect(validateAgainstSchema(schema, { name: 'abcd' })).toEqual(['args.name: too long']);
    expect(validateAgainstSchema(schema, { tags: [] })).toEqual(['args.tags: too few items']);
    expect(validateAgainstSchema(schema, { score: -1 })).toEqual(['args.score: below 0']);
    expect(validateAgainstSchema(schema, { score: 1.5, count: 1.5 })).toEqual(['args.count: expected integer']);
  });

  it('accepts anything for a schema with no type, and validates additionalProperties given as a schema', () => {
    expect(validateAgainstSchema({}, { a: [1, 'x'] })).toEqual([]);
    const open: JsonSchema = { type: 'object', additionalProperties: { type: 'number' } };
    expect(validateAgainstSchema(open, { a: 1, b: 2 })).toEqual([]);
    expect(validateAgainstSchema(open, { a: 'x' })).toEqual(['args.a: expected number']);
  });
});
