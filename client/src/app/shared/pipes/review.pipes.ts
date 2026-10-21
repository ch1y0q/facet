import { Pipe, PipeTransform } from '@angular/core';

import type { ReviewMark } from '../../features/gallery/gallery.store';

/**
 * The effective keep/remove mark of one photo on an annotated pin: the user's own
 * absolute choice, else the assistant's. Pure pipes (not component methods) so a
 * card re-evaluates only when a map is replaced, which is how the store updates them.
 */
@Pipe({ name: 'reviewMark', standalone: true, pure: true })
export class ReviewMarkPipe implements PipeTransform {
  transform(
    path: string,
    userMarks: ReadonlyMap<string, ReviewMark>,
    agentMarks: ReadonlyMap<string, ReviewMark>,
  ): ReviewMark | null {
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

/** Whether the user's own mark on a photo differs from the assistant's (false when either is absent). */
@Pipe({ name: 'reviewChanged', standalone: true, pure: true })
export class ReviewChangedPipe implements PipeTransform {
  transform(
    path: string,
    userMarks: ReadonlyMap<string, ReviewMark>,
    agentMarks: ReadonlyMap<string, ReviewMark>,
  ): boolean {
    const user = userMarks.get(path);
    const agent = agentMarks.get(path);
    return user !== undefined && agent !== undefined && user !== agent;
  }
}

/** Effective counts of one review group, derived from the marks. */
export interface ReviewGroupCount {
  count: number;
  keep: number;
  remove: number;
}

/** A translation key plus its parameters, to be fed to the `translate` pipe. */
export interface ReviewGroupHeaderText {
  key: string;
  params: Record<string, number>;
}

/**
 * Header text of one group section: the counted form when the pin carries marks, else the
 * bare title. Returns the key and params rather than the translated string so the pipe stays pure.
 */
@Pipe({ name: 'reviewGroupHeader', standalone: true, pure: true })
export class ReviewGroupHeaderPipe implements PipeTransform {
  transform(
    group: number,
    counts: ReadonlyMap<number, ReviewGroupCount>,
    withCounts: boolean,
  ): ReviewGroupHeaderText {
    const c = counts.get(group);
    if (!withCounts || !c) {
      return { key: 'gallery.pinned.review.group_title', params: { group } };
    }
    return {
      key: c.count === 1
        ? 'gallery.pinned.review.group_header'
        : 'gallery.pinned.review.group_header_plural',
      params: { group, count: c.count, keep: c.keep, remove: c.remove },
    };
  }
}

/** Translation key of a strip's aria-label: the grouped wording only when the pin carries groups. */
@Pipe({ name: 'reviewAriaKey', standalone: true, pure: true })
export class ReviewAriaKeyPipe implements PipeTransform {
  transform(mark: ReviewMark, group: number | null): string {
    const base = mark === 'keep' ? 'gallery.pinned.review.keep_aria' : 'gallery.pinned.review.remove_aria';
    return group === null ? `${base}_ungrouped` : base;
  }
}
