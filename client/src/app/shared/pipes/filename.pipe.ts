import { Pipe, PipeTransform } from '@angular/core';

/** Display a native photo filename while callers retain the original path as identity. */
@Pipe({ name: 'filename', standalone: true, pure: true })
export class FilenamePipe implements PipeTransform {
  transform(path: string): string {
    const separator = Math.max(path.lastIndexOf('/'), path.lastIndexOf('\\'));
    return path.slice(separator + 1);
  }
}
