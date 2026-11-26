#include <assert.h>
#include <stdint.h>
#include <string.h>
#include "common/matrix.h"

static void assert_equal(const struct matrix *a, const struct matrix *b)
{
    assert(a->rows == b->rows && a->columns == b->columns);
    assert(memcmp(a->data,b->data,sizeof(a->data)) == 0);
}

int main(void)
{
    struct matrix a = {.rows=2,.columns=3,.data={1,2,3,4,5,6}};
    struct matrix b = {.rows=3,.columns=2,.data={7,8,9,10,11,12}};
    struct matrix out = {.rows=2,.columns=2};
    assert(matrix_get(&a,0,0) == 1 && matrix_get(&a,1,2) == 6);
    matrix_set(&a,1,1,-5);
    assert(matrix_get(&a,1,1) == -5);
    assert(matrix_get(&a,1,0) == 4 && matrix_get(&a,1,2) == 6);
    matrix_set(&a,1,1,5);
    const struct matrix expected = {.rows=2,.columns=2,.data={58,64,139,154}};
    assert(matrix_multiply(&a,&b,&out));
    assert_equal(&out,&expected);

    struct matrix transposed = {.rows=3,.columns=2};
    const struct matrix expected_transpose = {.rows=3,.columns=2,.data={1,4,2,5,3,6}};
    assert(matrix_transpose(&a,&transposed));
    assert_equal(&transposed,&expected_transpose);

    struct matrix square = {.rows=2,.columns=2,.data={1,2,3,4}};
    const struct matrix squared = {.rows=2,.columns=2,.data={7,10,15,22}};
    assert(matrix_multiply(&square,&square,&out));
    assert_equal(&out,&squared);

    struct matrix vector = {.rows=3,.columns=1,.data={-1,2,0}};
    struct matrix result = {.rows=2,.columns=1};
    assert(matrix_multiply(&a,&vector,&result));
    assert(matrix_get(&result,0,0) == 3 && matrix_get(&result,1,0) == 6);
    struct matrix row = {.rows=1,.columns=3,.data={-1,2,0}};
    struct matrix scalar = {.rows=1,.columns=1};
    assert(matrix_multiply(&row,&vector,&scalar));
    assert(matrix_get(&scalar,0,0) == 5);

    // Assignment owns independent storage, including after the source scope ends.
    struct matrix copy;
    {
        struct matrix local = a;
        copy = local;
        matrix_set(&local,0,0,999);
    }
    assert_equal(&copy,&a);
    matrix_set(&copy,0,0,123);
    assert(matrix_get(&a,0,0) == 1);

    const struct matrix before = out;
    assert(!matrix_multiply(NULL,&b,&out));
    assert(!matrix_multiply(&a,NULL,&out));
    assert(!matrix_multiply(&a,&b,NULL));
    assert(!matrix_multiply(&a,&a,&out));
    struct matrix bad = {.rows=0,.columns=2};
    assert(!matrix_multiply(&bad,&b,&out));
    bad = (struct matrix){.rows=2,.columns=0};
    assert(!matrix_transpose(&bad,&out));
    bad = (struct matrix){.rows=MATRIX_MAX_ROWS+1,.columns=1};
    assert(!matrix_multiply(&bad,&b,&out));
    bad = (struct matrix){.rows=1,.columns=MATRIX_MAX_COLUMNS+1};
    assert(!matrix_transpose(&bad,&out));
    bad = (struct matrix){.rows=SIZE_MAX,.columns=3};
    assert(!matrix_multiply(&bad,&b,&out));
    bad = (struct matrix){.rows=1,.columns=4};
    assert(!matrix_multiply(&a,&b,&bad));
    assert(!matrix_transpose(&a,&out));
    assert(!matrix_transpose(NULL,&out));
    assert(!matrix_transpose(&a,NULL));
    assert_equal(&out,&before);

    const struct matrix saved = square;
    assert(!matrix_multiply(&square,&square,&square));
    assert(!matrix_multiply(&square,&out,&out));
    assert(!matrix_multiply(&out,&square,&out));
    assert(!matrix_transpose(&square,&square));
    assert_equal(&square,&saved);
    assert_equal(&out,&before);

    // Maximum dimensions and the final storage element remain usable.
    struct matrix full = {.rows=MATRIX_MAX_ROWS,.columns=MATRIX_MAX_COLUMNS};
    struct matrix full_transpose = {.rows=MATRIX_MAX_COLUMNS,.columns=MATRIX_MAX_ROWS};
    matrix_set(&full,MATRIX_MAX_ROWS-1,MATRIX_MAX_COLUMNS-1,42);
    assert(matrix_transpose(&full,&full_transpose));
    assert(matrix_get(&full_transpose,MATRIX_MAX_COLUMNS-1,MATRIX_MAX_ROWS-1) == 42);
    return 0;
}
