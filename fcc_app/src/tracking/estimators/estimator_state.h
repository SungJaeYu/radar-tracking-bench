#ifndef ESTIMATOR_STATE_H
#define ESTIMATOR_STATE_H

// CMake selects the matching implementation. State is owned inline so that
// copying a track also copies its filter; no allocation or external storage.
#if defined(CONFIG_RADAR_ESTIMATOR_EKF_CV) && defined(CONFIG_RADAR_ESTIMATOR_KF_CV)
#error "Select exactly one estimator implementation"
#endif

#if defined(CONFIG_RADAR_ESTIMATOR_EKF_CV)
#include "tracking/estimators/filters/ekf_cv_2d.h"
struct estimator {
    struct ekf_cv_2d_filter filter;
};
#else
#include "tracking/estimators/filters/kf_cv_1d.h"
struct estimator {
    struct kf_cv_1d_filter range_filter;
    struct kf_cv_1d_filter azimuth_filter;
};
#endif

#endif
