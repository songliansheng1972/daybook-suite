/* Daybook - qijuzhu indexer.  K&R C, works on 1970s Unix to today.
 * Daybook - 起居注索引器。K&R C，从 1970 年代的 Unix 一直用到今天。
 * cc daybook.c -o daybook ; ./daybook file1 file2 ...
 * 编译：cc daybook.c -o daybook ; 运行：./daybook file1 file2 ...
 */
#include <stdio.h>
#define MAXL 4096
int main(argc, argv)
int argc; char **argv;
{
    int i, ln, n;
    char line[MAXL], t[24], cls[64], title[128], *p, *q;
    printf("volume\tline\ttime\tcategory\ttitle\n");
    for (i = 1; i < argc; i++) {
        FILE *f = fopen(argv[i], "r");
        if (f == NULL) continue;
        ln = 0;
        while (fgets(line, MAXL, f) != NULL) {
            ln++;
            if (line[0] != '[') continue;
            if (line[5] != '-' || line[11] != ' ' || line[14] != ':') continue;
            for (n = 0; n < 16; n++) t[n] = line[n+1];
            t[16] = 0;
            cls[0] = 0; title[0] = 0;
            p = line + 17;
            while (*p == ' ') p++;
            if (*p == '[') {
                q = p + 1; n = 0;
                while (*q && *q != ']' && n < 63) cls[n++] = *q++;
                cls[n] = 0;
                if (*q == ']') q++;
                while (*q == ' ') q++;
                if (*q == '[') {
                    q++; n = 0;
                    while (*q && *q != ']' && n < 127) title[n++] = *q++;
                    title[n] = 0;
                }
            }
            printf("%s\t%d\t%s\t%s\t%s\n", argv[i], ln, t, cls, title);
        }
        fclose(f);
    }
    return 0;
}
