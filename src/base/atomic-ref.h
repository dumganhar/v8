// Copyright 2026 the V8 project authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef V8_BASE_ATOMIC_REF_H_
#define V8_BASE_ATOMIC_REF_H_

#include <atomic>
#include <type_traits>

namespace v8::base {

#if defined(__cpp_lib_atomic_ref)

template <typename T>
using AtomicRef = std::atomic_ref<T>;

#else

namespace atomic_ref_internal {

constexpr int ToBuiltinMemoryOrder(std::memory_order order) {
  if (order == std::memory_order_relaxed) return __ATOMIC_RELAXED;
  if (order == std::memory_order_consume) return __ATOMIC_CONSUME;
  if (order == std::memory_order_acquire) return __ATOMIC_ACQUIRE;
  if (order == std::memory_order_release) return __ATOMIC_RELEASE;
  if (order == std::memory_order_acq_rel) return __ATOMIC_ACQ_REL;
  return __ATOMIC_SEQ_CST;
}

constexpr std::memory_order CompareExchangeFailureOrder(
    std::memory_order order) {
  if (order == std::memory_order_release) return std::memory_order_relaxed;
  if (order == std::memory_order_acq_rel) return std::memory_order_acquire;
  return order;
}

}  // namespace atomic_ref_internal

// Android NDK r28c's libc++ does not implement C++20 std::atomic_ref. Clang's
// atomic builtins provide the same operations without changing the lifetime or
// type of the referenced object.
template <typename T>
class AtomicRef {
  static_assert(std::is_trivially_copyable_v<T>);

 public:
  explicit AtomicRef(T& value) : ptr_(&value) {}

  void store(T value,
             std::memory_order order = std::memory_order_seq_cst) const {
    __atomic_store(ptr_, &value,
                   atomic_ref_internal::ToBuiltinMemoryOrder(order));
  }

  T load(std::memory_order order = std::memory_order_seq_cst) const {
    T value;
    __atomic_load(ptr_, &value,
                  atomic_ref_internal::ToBuiltinMemoryOrder(order));
    return value;
  }

  T exchange(T value,
             std::memory_order order = std::memory_order_seq_cst) const {
    T old_value;
    __atomic_exchange(ptr_, &value, &old_value,
                      atomic_ref_internal::ToBuiltinMemoryOrder(order));
    return old_value;
  }

  bool compare_exchange_strong(T& expected, T desired,
                               std::memory_order success,
                               std::memory_order failure) const {
    return __atomic_compare_exchange(
        ptr_, &expected, &desired, false,
        atomic_ref_internal::ToBuiltinMemoryOrder(success),
        atomic_ref_internal::ToBuiltinMemoryOrder(failure));
  }

  bool compare_exchange_strong(
      T& expected, T desired,
      std::memory_order order = std::memory_order_seq_cst) const {
    return compare_exchange_strong(
        expected, desired, order,
        atomic_ref_internal::CompareExchangeFailureOrder(order));
  }

  T fetch_or(T value,
             std::memory_order order = std::memory_order_seq_cst) const {
    return __atomic_fetch_or(ptr_, value,
                             atomic_ref_internal::ToBuiltinMemoryOrder(order));
  }

  T fetch_add(T value,
              std::memory_order order = std::memory_order_seq_cst) const {
    return __atomic_fetch_add(ptr_, value,
                              atomic_ref_internal::ToBuiltinMemoryOrder(order));
  }

 private:
  T* ptr_;
};

#endif  // defined(__cpp_lib_atomic_ref)

}  // namespace v8::base

#endif  // V8_BASE_ATOMIC_REF_H_
