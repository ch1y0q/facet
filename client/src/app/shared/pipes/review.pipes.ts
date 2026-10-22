import { Pipe, PipeTransform } from '@angular/core';

import type { CullReason } from '../../features/gallery/burst-culling.pipes';
import { REVIEW_KEEP_WHOLE_KINDS } from '../../features/gallery/gallery.store';
import type {
  AppliedGroup, AppliedMark, AppliedReceipt, ApplyUnit, ReviewGroupLabel, ReviewMark, ReviewReason,
} from '../../features/gallery/gallery.store';

/**
 * The effective keep/remove mark of one photo on an annotated pin: what Apply committed, else the user's own
 * absolute choice, else the assistant's. Pure pipes (not component methods) so a
 * card re-evaluates only when a map is replaced, which is how the store updates them.
 */
@Pipe({ name: 'reviewMark', standalone: true, pure: true })
export class ReviewMarkPipe implements PipeTransform {
  transform(
    path: string,
    userMarks: ReadonlyMap<string, ReviewMark>,
    agentMarks: ReadonlyMap<string, ReviewMark>,
    applied: ReadonlyMap<string, AppliedMark> = new Map(),
  ): ReviewMark | null {
    return applied.get(path)?.mark ?? userMarks.get(path) ?? agentMarks.get(path) ?? null;
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

/** Translation key plus params of one group's assistant heading, or null when the pin carries none. */
@Pipe({ name: 'reviewGroupLabel', standalone: true, pure: true })
export class ReviewGroupLabelPipe implements PipeTransform {
  transform(group: number, labels: ReadonlyMap<number, ReviewGroupLabel>): ReviewGroupLabel | null {
    const label = labels.get(group);
    return label ? { key: `culling.group_reason.${label.key}`, params: label.params } : null;
  }
}

/** The assistant's reason for one photo in the shape the cull-reason pipe translates, or null. */
@Pipe({ name: 'reviewReason', standalone: true, pure: true })
export class ReviewReasonPipe implements PipeTransform {
  transform(path: string, reasons: ReadonlyMap<string, ReviewReason>): CullReason | null {
    const reason = reasons.get(path);
    return reason ? { key: reason.key, value: reason.value ?? null } : null;
  }
}

/** Whether a group is a bracket / panorama set the cull keeps whole. */
@Pipe({ name: 'reviewGroupKeptWhole', standalone: true, pure: true })
export class ReviewGroupKeptWholePipe implements PipeTransform {
  transform(group: number, kinds: ReadonlyMap<number, string>): boolean {
    return REVIEW_KEEP_WHOLE_KINDS.has(kinds.get(group) ?? '');
  }
}

/** Whether the user already applied this photo: its Keep / Remove strip and the K / R keys are inert. */
@Pipe({ name: 'reviewPathLocked', standalone: true, pure: true })
export class ReviewPathLockedPipe implements PipeTransform {
  transform(path: string, applied: ReadonlyMap<string, AppliedMark>): boolean {
    return applied.has(path);
  }
}

/** Whether every pinned photo of a group was applied. */
@Pipe({ name: 'reviewGroupApplied', standalone: true, pure: true })
export class ReviewGroupAppliedPipe implements PipeTransform {
  transform(group: number, groups: ReadonlyMap<number, AppliedGroup>): boolean {
    return groups.has(group);
  }
}

/** The receipt summary of an applied group (kept-whole count, availability), or null when it is not applied. */
@Pipe({ name: 'reviewGroupReceipt', standalone: true, pure: true })
export class ReviewGroupReceiptPipe implements PipeTransform {
  transform(group: number, groups: ReadonlyMap<number, AppliedGroup>): AppliedGroup | null {
    return groups.get(group) ?? null;
  }
}

/** What Apply would send for one group, or null when the group has nothing left to apply. */
@Pipe({ name: 'reviewApplyPlan', standalone: true, pure: true })
export class ReviewApplyPlanPipe implements PipeTransform {
  transform(group: number, plan: ReadonlyMap<number, ApplyUnit>): ApplyUnit | null {
    return plan.get(group) ?? null;
  }
}

/** Key plus params naming an applied group in the status line's menu: its assistant heading, else its number. */
@Pipe({ name: 'reviewReceiptLabel', standalone: true, pure: true })
export class ReviewReceiptLabelPipe implements PipeTransform {
  transform(receipt: AppliedReceipt): ReviewGroupLabel {
    if (receipt.label) return { key: `culling.group_reason.${receipt.label.key}`, params: receipt.label.params };
    if (receipt.group === null) return { key: 'gallery.pinned.review.applied_marks_only', params: {} };
    return { key: 'gallery.pinned.review.group_title', params: { group: receipt.group } };
  }
}

/** The "Group N" title of an applied receipt whose menu entry also carries the assistant's heading, else null. */
@Pipe({ name: 'reviewReceiptTitle', standalone: true, pure: true })
export class ReviewReceiptTitlePipe implements PipeTransform {
  transform(receipt: AppliedReceipt): ReviewGroupLabel | null {
    return receipt.label && receipt.group !== null
      ? { key: 'gallery.pinned.review.group_title', params: { group: receipt.group } }
      : null;
  }
}
