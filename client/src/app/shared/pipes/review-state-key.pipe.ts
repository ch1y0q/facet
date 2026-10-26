import { Pipe, PipeTransform } from '@angular/core';
import { i18nKeys } from '../../core/i18n/keys';

/** i18n key of the review decision a history snapshot [stars, favorite, rejected, kept] carries. */
@Pipe({ name: 'reviewStateKey', standalone: true, pure: true })
export class ReviewStateKeyPipe implements PipeTransform {
  private readonly I18N = i18nKeys();

  transform(snapshot: (string | number | null)[]): string {
    if (snapshot[2]) return this.I18N.organization_history.rejected;
    return snapshot[3] ? this.I18N.organization_history.kept : this.I18N.culling.lightbox.undecided;
  }
}
