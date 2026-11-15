-- models/marts/fct_orders.sql
{{ config(materialized='incremental') }}
select * from {{ ref('stg_orders') }}
