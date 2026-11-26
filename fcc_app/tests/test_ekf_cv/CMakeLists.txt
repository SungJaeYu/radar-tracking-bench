cmake_minimum_required(VERSION 3.20.0)
project(test_ekf_cv C)
enable_testing()
add_executable(ekf_cv_tests src/main.c ../../src/tracking/estimators/filters/ekf_cv_2d.c
    ../../src/common/matrix.c ../../src/tracking/estimators/filters/kf_cv_1d.c ../../src/tracking/angle_utils.c)
target_include_directories(ekf_cv_tests PRIVATE ../../src ../common/include)
target_compile_features(ekf_cv_tests PRIVATE c_std_99)
target_compile_options(ekf_cv_tests PRIVATE -Wall -Wextra -Werror -UNDEBUG)
target_link_libraries(ekf_cv_tests PRIVATE m)
add_test(NAME ekf_cv_predict COMMAND ekf_cv_tests)

add_executable(ekf_cv_correct_tests src/correct.c ../../src/tracking/estimators/filters/ekf_cv_2d.c
    ../../src/common/matrix.c ../../src/tracking/angle_utils.c)
target_include_directories(ekf_cv_correct_tests PRIVATE ../../src ../common/include)
target_compile_features(ekf_cv_correct_tests PRIVATE c_std_99)
target_compile_options(ekf_cv_correct_tests PRIVATE -Wall -Wextra -Werror -UNDEBUG)
target_link_libraries(ekf_cv_correct_tests PRIVATE m)
add_test(NAME ekf_cv_correct COMMAND ekf_cv_correct_tests)
