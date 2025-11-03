// generated from rosidl_generator_cpp/resource/idl__builder.hpp.em
// with input from leap_hand:srv/LeapPosVelEff.idl
// generated code does not contain a copyright notice

#ifndef LEAP_HAND__SRV__DETAIL__LEAP_POS_VEL_EFF__BUILDER_HPP_
#define LEAP_HAND__SRV__DETAIL__LEAP_POS_VEL_EFF__BUILDER_HPP_

#include <algorithm>
#include <utility>

#include "leap_hand/srv/detail/leap_pos_vel_eff__struct.hpp"
#include "rosidl_runtime_cpp/message_initialization.hpp"


namespace leap_hand
{

namespace srv
{


}  // namespace srv

template<typename MessageType>
auto build();

template<>
inline
auto build<::leap_hand::srv::LeapPosVelEff_Request>()
{
  return ::leap_hand::srv::LeapPosVelEff_Request(rosidl_runtime_cpp::MessageInitialization::ZERO);
}

}  // namespace leap_hand


namespace leap_hand
{

namespace srv
{

namespace builder
{

class Init_LeapPosVelEff_Response_effort
{
public:
  explicit Init_LeapPosVelEff_Response_effort(::leap_hand::srv::LeapPosVelEff_Response & msg)
  : msg_(msg)
  {}
  ::leap_hand::srv::LeapPosVelEff_Response effort(::leap_hand::srv::LeapPosVelEff_Response::_effort_type arg)
  {
    msg_.effort = std::move(arg);
    return std::move(msg_);
  }

private:
  ::leap_hand::srv::LeapPosVelEff_Response msg_;
};

class Init_LeapPosVelEff_Response_velocity
{
public:
  explicit Init_LeapPosVelEff_Response_velocity(::leap_hand::srv::LeapPosVelEff_Response & msg)
  : msg_(msg)
  {}
  Init_LeapPosVelEff_Response_effort velocity(::leap_hand::srv::LeapPosVelEff_Response::_velocity_type arg)
  {
    msg_.velocity = std::move(arg);
    return Init_LeapPosVelEff_Response_effort(msg_);
  }

private:
  ::leap_hand::srv::LeapPosVelEff_Response msg_;
};

class Init_LeapPosVelEff_Response_position
{
public:
  Init_LeapPosVelEff_Response_position()
  : msg_(::rosidl_runtime_cpp::MessageInitialization::SKIP)
  {}
  Init_LeapPosVelEff_Response_velocity position(::leap_hand::srv::LeapPosVelEff_Response::_position_type arg)
  {
    msg_.position = std::move(arg);
    return Init_LeapPosVelEff_Response_velocity(msg_);
  }

private:
  ::leap_hand::srv::LeapPosVelEff_Response msg_;
};

}  // namespace builder

}  // namespace srv

template<typename MessageType>
auto build();

template<>
inline
auto build<::leap_hand::srv::LeapPosVelEff_Response>()
{
  return leap_hand::srv::builder::Init_LeapPosVelEff_Response_position();
}

}  // namespace leap_hand

#endif  // LEAP_HAND__SRV__DETAIL__LEAP_POS_VEL_EFF__BUILDER_HPP_
