#include "common/matrix.h"

static bool matrix_valid(const struct matrix *matrix);

bool matrix_multiply(const struct matrix *a, const struct matrix *b, struct matrix *out)
{
    if (!matrix_valid(a) || !matrix_valid(b) || !matrix_valid(out) ||
        a->columns != b->rows || out->rows != a->rows || out->columns != b->columns ||
        out == a || out == b) {
        return false;
    }

    for (size_t row = 0; row < out->rows; ++row) {
        for (size_t column = 0; column < out->columns; ++column) {
            float sum = 0.0f;
            for (size_t index = 0; index < a->columns; ++index) {
                sum += a->data[row * a->columns + index] * b->data[index * b->columns + column];
            }
            out->data[row * out->columns + column] = sum;
        }
    }
    return true;
}

bool matrix_transpose(const struct matrix *input, struct matrix *out)
{
    if (!matrix_valid(input) || !matrix_valid(out) ||
        out->rows != input->columns || out->columns != input->rows ||
        out == input) {
        return false;
    }

    for (size_t row = 0; row < input->rows; ++row) {
        for (size_t column = 0; column < input->columns; ++column) {
            out->data[column * out->columns + row] = input->data[row * input->columns + column];
        }
    }
    return true;
}

static bool matrix_valid(const struct matrix *matrix)
{
    return matrix != NULL &&
           matrix->rows > 0 && matrix->rows <= MATRIX_MAX_ROWS &&
           matrix->columns > 0 && matrix->columns <= MATRIX_MAX_COLUMNS;
}
