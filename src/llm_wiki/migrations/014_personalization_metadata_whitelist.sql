update personalization_settings
   set metadata = jsonb_build_object(
     'workflow_mode',
     case
       when metadata->>'workflow_mode' in ('generic', 'personal') then metadata->>'workflow_mode'
       else 'generic'
     end,
     'profile',
     jsonb_build_object(
       'frequent_people',
       case
         when jsonb_typeof(metadata #> '{profile,frequent_people}') = 'array'
         then metadata #> '{profile,frequent_people}'
         else '[]'::jsonb
       end,
       'frequent_places',
       case
         when jsonb_typeof(metadata #> '{profile,frequent_places}') = 'array'
         then metadata #> '{profile,frequent_places}'
         else '[]'::jsonb
       end,
       'active_projects',
       case
         when jsonb_typeof(metadata #> '{profile,active_projects}') = 'array'
         then metadata #> '{profile,active_projects}'
         else '[]'::jsonb
       end,
       'life_categories',
       case
         when jsonb_typeof(metadata #> '{profile,life_categories}') = 'array'
         then metadata #> '{profile,life_categories}'
         else '[]'::jsonb
       end
     )
   )
 where id = 'default';
