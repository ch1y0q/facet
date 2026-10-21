import { Pipe, PipeTransform } from '@angular/core';

export type ReviewMarkValue = 'keep' | 'remove';

/**
 * The effective keep/remove mark of one photo on an annotated pin: the user's own
 * absolute choice, else the assistant's. Pure pipes (not component methods) so a
 * card re-evaluates only when a map is replaced, which is how the store updates them.
 */
@Pipe({ name: 'reviewMark', standalone: true, pure: true })
export class ReviewMarkPipe implements PipeTransform {
  transform(
    path: string,
    userMarks: ReadonlyMap<string, ReviewMarkValue>,
    agentMarks: ReadonlyMap<string, ReviewMarkValue>,
  ): ReviewMarkValue | null {
    return userMarks.get(path) ?? agentMarks.get(path) ?? null;
  }
}

/** The assistant's group number of one photo, or null when the pin carries none. */
@Pipe({ name: 'reviewGroup', standalone: true, pure: true })
export class ReviewGroupPipe implements PipeTransform {
  transform(path: string, groups: ReadonlyMap<string, number>): number | null {
    return groups.get(path) ?? null;
  }
}
