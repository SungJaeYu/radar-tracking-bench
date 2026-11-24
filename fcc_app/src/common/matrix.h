#ifndef MATRIX_H
#define MATRIX_H

#include <stdbool.h>
#include <stddef.h>

#define MATRIX_MAX_ROWS 4U
#define MATRIX_MAX_COLUMNS 4U
#define MATRIX_MAX_ELEMENTS (MATRIX_MAX_ROWS * MATRIX_MAX_COLUMNS)

// Owns fixed storage. Active elements are packed in row-major order using columns
// as the stride. Initialize rows/columns and data together; assignment copies data.
struct matrix {
    size_t rows;
    size_t columns;
    float data[MATRIX_MAX_ELEMENTS];
};

// Require valid dimensions and row < rows, column < columns.
// Element access does not perform bounds checks.
static inline float matrix_get(const struct matrix *matrix, size_t row, size_t column)
{
    return matrix->data[row * matrix->columns + column];
}

static inline void matrix_set(struct matrix *matrix, size_t row, size_t column, float value)
{
    matrix->data[row * matrix->columns + column] = value;
}

// Compute out = a * b. Output dimensions must be a.rows by b.columns.
// Inputs may be the same matrix; output must be a separate matrix object.
// Return false for NULL pointers, zero/over-capacity dimensions, incompatible
// dimensions, or output aliasing an input. On failure, leave output unchanged.
bool matrix_multiply(const struct matrix *a, const struct matrix *b, struct matrix *out);

// Compute out = input transpose. Output dimensions must be input.columns by input.rows.
// Same validation/failure rules as multiply; in-place transpose is not supported.
bool matrix_transpose(const struct matrix *input, struct matrix *out);

#endif
