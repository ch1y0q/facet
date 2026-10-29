import { Pipe, PipeTransform } from '@angular/core';
import { basename } from '../utils/clipboard';

/** Display a native photo filename while callers retain the original path as identity. */
@Pipe({ name: 'filename', standalone: true, pure: true })
export class FilenamePipe implements PipeTransform {
  transform(path: string): string {
    return basename(path);
  }
}
